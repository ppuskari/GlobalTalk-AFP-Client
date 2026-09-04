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

python3 "$ROOT/tools/apply_ddp_transport.py" "$CLIENT"

echo
echo "Patched tree: $CLIENT"
echo "Next: $ROOT/scripts/build-linux.sh"
