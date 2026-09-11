#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7d-finder-recovery-did"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7d.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# Generate and validate the known-good R7C tree first.
sh "$ROOT/scripts/build-r7c-finder-did.sh"

# Layer recovery-only DID reconstruction on the generated source.
python3 "$ROOT/tools/apply_finder_recovery_did_r7d.py" "$CLIENT"

grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

grep 'R7D: metadata recovery DID-prime' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7D: file recovery DID-prime' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7D: directory-stat recovery DID-prime' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7D: directory-list recovery DID-prime' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

# Recompile the already-generated tree without reconstructing lowlevel/did.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

# Ensure the final compile source kept R7C and R7D.
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/lowlevel.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
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
    "$ROOT/tools/apply_finder_atp_retry_r7a.py" \
    "$ROOT/tools/apply_finder_enum_metadata_r7b.py" \
    "$ROOT/tools/apply_finder_did_cache_r7c.py" \
    "$ROOT/tools/apply_finder_recovery_did_r7d.py"

sh -n "$ROOT/scripts/gt-pull-r7d.sh"

echo
echo "R7D Finder recovery-DID build ready."
echo "R7C ParentDirID/DID reuse: retained"
echo "After recovery: parent DID chain rebuilt root-to-leaf"
echo "Metadata retry after recovery: DID-prime enabled"
echo "File retry after recovery: DID-prime enabled"
echo "Directory stat/list retry after recovery: DID-prime enabled"
echo "Normal persistent-session traffic: unchanged"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo "R4 resource-fork stream: retained"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7d.sh 'AFP_URL' 'DEST'"
