#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

if [ ! -d "$CLIENT" ]; then
    echo "Run scripts/bootstrap-linux.sh first." >&2
    exit 1
fi

cd "$CLIENT"
rm -rf build
meson setup build
meson compile -C build

echo
echo "Build complete."
echo "Example:"
echo "  build/cmdline/afpcmd 'afp+ddp://OBJECT@ZONE'"
