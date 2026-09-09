#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Layer the existing AFP 2.x date normalization first, then add diagnostics
# that only log the raw server/file date words.  The native ATP/session-R2/R4
# transport remains untouched.
python3 "$ROOT/tools/apply_afp2_date_normalization_r1.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp2_date_wire_diag.py" "$CLIENT"

sh "$ROOT/scripts/build-native-atp-r1.sh"

grep 'GLOBALTALK AFP2 DATE NORMALIZATION R1' \
    "$CLIENT/include/afp.h" >/dev/null
grep 'GLOBALTALK AFP2 DATE WIRE DIAG R1' \
    "$CLIENT/lib/proto_server.c" >/dev/null
grep 'GLOBALTALK AFP2 DATE WIRE DIAG R1' \
    "$CLIENT/lib/proto_replyblock.c" >/dev/null
grep 'GLOBALTALK NETATALK FILEDATES R1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

echo
echo "File Dates R3 diagnostic build ready."
echo "AFP 2.x server-clock normalization: enabled"
echo "AppleDouble create/modify preservation: enabled"
echo "Raw AFP date tracing: enabled when GT_AFP_DATE_TRACE is set"
echo "Native ATP/session-R2/R4 transport: unchanged"
echo
echo "For a clean trace:"
echo "  export GT_AFP_DATE_TRACE=/tmp/gt-afp-date-wire.log"
echo "  rm -f /tmp/gt-afp-date-wire.log"
echo "  ./scripts/gt-afp-reset.sh"
echo "  run one gt-afp-ls request"
