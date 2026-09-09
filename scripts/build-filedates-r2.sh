#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# File Dates R2 adds only the post-0.9.5 AFP 2.x server-clock date
# normalization before the existing native/session-R2 + AppleDouble File Dates
# build.  This intentionally leaves the proven ATP/ASP transport untouched.
python3 "$ROOT/tools/apply_afp2_date_normalization_r1.py" "$CLIENT"

sh "$ROOT/scripts/build-native-atp-r1.sh"

grep 'GLOBALTALK AFP2 DATE NORMALIZATION R1' \
    "$CLIENT/include/afp.h" >/dev/null
grep 'GLOBALTALK NETATALK FILEDATES R1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 "$ROOT/tests/test_afp2_date_normalization_model.py"

echo
echo "File Dates R2 test build ready."
echo "AFP 2.x server-clock normalization: enabled"
echo "AppleDouble create/modify preservation: enabled"
echo "Native ATP/session-R2/R4 transport: unchanged"
echo
echo "IMPORTANT: restart an already-running afpsld before field testing"
echo "so the new protocol date decoder is actually loaded."
