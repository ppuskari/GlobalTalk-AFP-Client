#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# User-friendly archive destination.  The Python browser appends the selected
# file/directory leaf to this root for g N, and the current directory leaf for d.
: "${GT_AFP_DOWNLOAD_ROOT:=/mnt/AFPSERVER/128G2/AFPFILES2}"
export GT_AFP_DOWNLOAD_ROOT

exec python3 "$ROOT/scripts/gt-afp-browser.py" "$@"
