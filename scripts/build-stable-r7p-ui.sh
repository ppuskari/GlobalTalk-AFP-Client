#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

sh "$ROOT/scripts/build-stable-r7.sh"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-r7p.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable.py"
python3 -m py_compile "$ROOT/scripts/gt-afp-browser.py"

echo
echo "R7P authoritative progress UI validated."
echo "Run: $ROOT/scripts/gt-afp-browser.sh"
