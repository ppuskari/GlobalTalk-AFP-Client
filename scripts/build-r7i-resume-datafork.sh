#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7i-resume-datafork"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7i.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# Reconstruct the proven R7E tree from pinned Netatalk Client 0.9.5.
sh "$ROOT/scripts/build-r7e-zero-datafork.sh"

# Replace only the data-fork recovery path.  No healthy-path AFP operations,
# ATP timing, enumeration layout, metadata behavior, or resource-fork behavior
# are changed by R7I.
python3 "$ROOT/tools/apply_resume_datafork_r7i.py" "$CLIENT"

grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME DATAFORK R7I' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7I: resuming current file' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7I: resume validation passed' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

# Recompile the already-generated R7E+R7I source without reconstructing it.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

# Final source must retain the full proven stack plus R7I only on recovery.
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME DATAFORK R7I' \
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
    "$ROOT/tools/apply_resume_datafork_r7i.py"
sh -n "$ROOT/scripts/gt-pull-r7i.sh"

echo
echo "R7I resumable data-fork recovery build ready."
echo "Base: virgin R7E behavior retained"
echo "Normal no-error path: unchanged"
echo "Recovery: preserve last successfully written byte offset"
echo "Recovery validation: fresh remote size + mtime must match"
echo "Recovery DID rebuild: retained"
echo "Per-file in-process recovery budget: 3"
echo "Known empty data forks: R7E skip retained"
echo "ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo "Metadata/resource-fork paths: unchanged"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7i.sh 'AFP_URL' 'DEST'"
