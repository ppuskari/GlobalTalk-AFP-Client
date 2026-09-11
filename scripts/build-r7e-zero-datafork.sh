#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7e-zero-datafork"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7e.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# Generate and validate the complete R7D tree first.
sh "$ROOT/scripts/build-r7d-finder-recovery-did.sh"

# Layer only the known-empty data-fork transaction elimination.
python3 "$ROOT/tools/apply_zero_datafork_skip_r7e.py" "$CLIENT"

grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7E: empty data fork; skipping AFP open/read/close' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

# Recompile the generated source without erasing R7C/R7D.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

# Verify the final compile source retained the complete stack.
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' \
    "$CLIENT/lib/asp_transport.c")" -eq 2

for binary in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta
do
    strings "$OUT/$binary" | grep 'GLOBALTALK NATIVE ATP R1' >/dev/null || {
        echo "ERROR: native ATP marker missing from $binary" >&2
        exit 1
    }
done

python3 -m py_compile \
    "$ROOT/tools/apply_finder_recovery_did_r7d.py" \
    "$ROOT/tools/apply_zero_datafork_skip_r7e.py"

sh -n "$ROOT/scripts/gt-pull-r7e.sh"

echo
echo "R7E zero-data-fork build ready."
echo "R7D recovery DID rebuild: retained"
echo "Known empty data forks: AFP open/read/close skipped"
echo "FinderInfo/resource forks/AppleDouble: unchanged and still copied"
echo "Nonzero data forks: unchanged"
echo "Exact data-fork size verification: retained"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo "R4 resource-fork stream: retained"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7e.sh 'AFP_URL' 'DEST'"
