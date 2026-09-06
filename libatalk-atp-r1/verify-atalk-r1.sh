#!/bin/sh
set -eu

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$SELF_DIR/.." && pwd)
LIB=${1:-"$REPO/legacy/atalk-r1/libatalk-atp-r1.a"}

test -f "$LIB" || {
    echo "ERROR: library not found: $LIB" >&2
    exit 1
}

echo "Archive: $LIB"
echo
echo "ATP members:"
ar t "$LIB" | grep '^atp_.*\.o$'
echo
echo "R1 symbols:"
nm -A "$LIB" | grep -E ' (atp_rsel|atp_rsel_legacy)$'
echo
echo "SHA256:"
sha256sum "$LIB"
