#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK="$ROOT/work"
CLIENT="$WORK/netatalk-client"

mkdir -p "$WORK"

if [ ! -d "$CLIENT/.git" ]; then
    git clone \
      --branch 0.9.5 \
      --depth 1 \
      https://github.com/Netatalk/netatalk-client.git \
      "$CLIENT"
fi

cd "$CLIENT"

TAG=$(git describe --tags --exact-match 2>/dev/null || true)
if [ "$TAG" != "0.9.5" ]; then
    echo "Expected Netatalk Client 0.9.5, got: $TAG" >&2
    exit 1
fi

# Python 3.4 pathlib lacks Path.read_text()/write_text().  Install tiny
# compatibility shims before executing the guarded overlay patcher.
python3 - "$ROOT/tools/apply_ddp_transport.py" "$CLIENT" <<'PY'
import io
import pathlib
import runpy
import sys

if not hasattr(pathlib.Path, "read_text"):
    def read_text(self, encoding="utf-8", errors=None):
        with io.open(str(self), "r", encoding=encoding, errors=errors) as f:
            return f.read()
    pathlib.Path.read_text = read_text

if not hasattr(pathlib.Path, "write_text"):
    def write_text(self, data, encoding="utf-8", errors=None):
        with io.open(str(self), "w", encoding=encoding, errors=errors) as f:
            return f.write(data)
    pathlib.Path.write_text = write_text

script = sys.argv[1]
target = sys.argv[2]
sys.argv = [script, target]
runpy.run_path(script, run_name="__main__")
PY

echo
echo "Patched tree: $CLIENT"
echo "Next: $ROOT/scripts/build-linux.sh"
