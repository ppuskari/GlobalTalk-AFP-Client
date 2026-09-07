#!/bin/bash

# Jessie normally maps /bin/sh to dash. If this script is invoked as
# "sh scripts/benchmark-pagespinner-r4.sh", re-exec under Bash before using
# Bash-only PIPESTATUS so the documented command remains valid.
if [ -z "${BASH_VERSION:-}" ]; then
    exec /bin/bash "$0" "$@"
fi

set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${1:-"$ROOT/build-rfork-r4"}
BIN="$BUILD/gt-afp-pull"
OUTROOT=${OUTROOT:-/mnt/AFPSERVER/128G2/gt-afp-r4-test}
REMOTE='afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac/The Software!!/PageSpinner 3.0.2/PageSpinner'
EXPECTED_RSRC=2668283
EXPECTED_AD=2669024
AD_OFFSET=741

if [ ! -x "$BIN" ]; then
    echo "ERROR: build not found: $BIN" >&2
    echo "Run first: sh scripts/build-rfork-r4.sh" >&2
    exit 1
fi

mkdir -p "$OUTROOT"

# A stale afpsld may have an older BINDIR or transport implementation. Stop
# only this user's helper so the selected benchmark build launches its own.
pkill -TERM -u "$USER" -x afpsld 2>/dev/null || true
sleep 2
if pgrep -u "$USER" -x afpsld >/dev/null 2>&1; then
    pkill -KILL -u "$USER" -x afpsld
    sleep 1
fi

STAMP=$(date '+%Y%m%d-%H%M%S')
DEST="$OUTROOT/PageSpinner-r4-$STAMP"
LOG="$OUTROOT/pagespinner-r4-$STAMP.log"
mkdir -p "$DEST"

START=$(date +%s)

echo "Build:       $BUILD"
echo "Destination: $DEST"
echo "Log:         $LOG"
echo "Started:     $(date)"
echo

"$BIN" \
  -V -M netatalk \
  "$REMOTE" \
  "$DEST" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

END=$(date +%s)
ELAPSED=$((END - START))
ADFILE="$DEST/.AppleDouble/PageSpinner"
DATAFILE="$DEST/PageSpinner"

AD_SIZE=0
DATA_SIZE=0
if [ -f "$ADFILE" ]; then
    AD_SIZE=$(stat -c '%s' "$ADFILE")
fi
if [ -f "$DATAFILE" ]; then
    DATA_SIZE=$(stat -c '%s' "$DATAFILE")
fi

RSRC_COPIED=0
if [ "$AD_SIZE" -ge "$AD_OFFSET" ]; then
    RSRC_COPIED=$((AD_SIZE - AD_OFFSET))
fi

echo
echo "============================================================"
echo "PageSpinner R4 streaming result"
echo "============================================================"
echo "Exit code:              $RC"
echo "Elapsed seconds:        $ELAPSED"
echo "Data fork bytes:        $DATA_SIZE"
echo "AppleDouble bytes:      $AD_SIZE"
echo "Resource bytes copied:  $RSRC_COPIED"
echo "Expected resource:      $EXPECTED_RSRC"
echo "Expected AppleDouble:   $EXPECTED_AD"

if [ "$ELAPSED" -gt 0 ]; then
    awk -v bytes="$RSRC_COPIED" -v sec="$ELAPSED" 'BEGIN {
        printf "Effective resource rate: %.2f KiB/s  %.2f kbit/s\n", \
               bytes / sec / 1024.0, bytes * 8.0 / sec / 1000.0
    }'
fi

echo
echo "R3 baseline: 434 seconds / 49.18 kbit/s"
echo "R4 target:   approach the proven stateful data-fork rate"

echo
echo "----- Files -----"
find "$DEST" -type f -printf '%p %s bytes\n' | sort

STRUCT_RC=1
if [ -f "$ADFILE" ]; then
    python3 - "$ADFILE" "$EXPECTED_RSRC" "$AD_OFFSET" <<'PY'
from __future__ import print_function

import struct
import sys

path = sys.argv[1]
expected_length = int(sys.argv[2])
expected_offset = int(sys.argv[3])

with open(path, "rb") as f:
    hdr = f.read(26)
    if len(hdr) != 26:
        raise SystemExit(2)

    magic, version = struct.unpack(">II", hdr[:8])
    entries = struct.unpack(">H", hdr[24:26])[0]
    found = None

    print("magic:   0x%08x" % magic)
    print("version: 0x%08x" % version)
    print("entries: %d" % entries)

    for i in range(entries):
        raw = f.read(12)
        if len(raw) != 12:
            raise SystemExit(3)
        entry_id, offset, length = struct.unpack(">III", raw)
        if entry_id == 2:
            found = (offset, length)
            print("resource: offset=%d length=%d" % found)

if found != (expected_offset, expected_length):
    raise SystemExit(4)
PY
    STRUCT_RC=$?
fi

if [ "$RC" -eq 0 ] && \
   [ "$DATA_SIZE" -eq 0 ] && \
   [ "$AD_SIZE" -eq "$EXPECTED_AD" ] && \
   [ "$STRUCT_RC" -eq 0 ]; then
    echo
    echo "PASS: PageSpinner R4 correctness matches the proven R3/R2F baseline."
    exit 0
fi

echo
echo "FAIL: one or more PageSpinner correctness gates did not match." >&2
exit 1
