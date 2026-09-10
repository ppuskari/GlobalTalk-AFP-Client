#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# R4 keeps the standards-correct AFP 2.x date normalization, then layers an
# opt-in classic Finder-compatible read interpretation.  Transport remains
# untouched; upload date encoding remains standards-correct.
python3 "$ROOT/tools/apply_afp2_date_normalization_r1.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp2_legacy_date_compat_r4.py" "$CLIENT"

sh "$ROOT/scripts/build-native-atp-r1.sh"

grep 'GLOBALTALK AFP2 DATE NORMALIZATION R1' \
    "$CLIENT/include/afp.h" >/dev/null
grep 'GLOBALTALK AFP2 LEGACY DATE COMPAT R4' \
    "$CLIENT/lib/proto_server.c" >/dev/null
grep 'GLOBALTALK NETATALK FILEDATES R1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 "$ROOT/tests/test_afp2_date_normalization_model.py"
python3 "$ROOT/tests/test_afp2_legacy_date_compat_r4_model.py"
sh -n "$ROOT/scripts/gt-pull-direct.sh"
sh -n "$ROOT/scripts/gt-afp-reset.sh"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "File Dates R4 test build ready."
echo "Standards AFP 2.x date normalization: enabled"
echo "Classic Finder date compatibility: opt-in"
echo "  export GT_AFP_DATE_COMPAT=legacy1900"
echo "AppleDouble create/modify preservation: enabled"
echo "AFP write-side date encoding: unchanged"
echo "Native ATP/session-R2/R4 transport: unchanged"
echo "Resilient recursive pull retries: enabled"
echo "  default attempts: 3"
echo "  override: export GT_AFP_PULL_ATTEMPTS=N"
echo
echo "On recursive pull failure, gt-pull-direct.sh now:"
echo "  1. leaves completed/partial results in place"
echo "  2. safely restarts afpsld"
echo "  3. retries the same remote base"
echo "  4. refuses daemon reset if another AFP client is active"
echo
echo "IMPORTANT: restart afpsld after changing GT_AFP_DATE_COMPAT"
echo "so the daemon inherits the selected compatibility mode."
