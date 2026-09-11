#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7c-finder-did"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7c.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

test -f "$NATIVE_SRC" || {
    echo "ERROR: native ATP source missing: $NATIVE_SRC" >&2
    exit 1
}

# did.c/did.h were not historically reconstructed by build-native-atp-r1.sh.
# Force those two generated files back to pinned 0.9.5 here so repeated R7C
# builds cannot inherit a prior partial DID patch.
git -C "$CLIENT" show HEAD:lib/did.c > "$CLIENT/lib/did.c"
git -C "$CLIENT" show HEAD:lib/did.h > "$CLIENT/lib/did.h"

# First generate the complete known-good R7B/R7A/R6.4 tree.  This also resets
# lowlevel.c and the rest of the native generated sources to pinned 0.9.5.
GT_AFP_ENABLE_R7B=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

# Layer only the Finder-style DID reuse change onto that generated source.
python3 "$ROOT/tools/apply_finder_did_cache_r7c.py" "$CLIENT"

grep 'GLOBALTALK FINDER ENUM METADATA R7B' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK FINDER DID CACHE R7C' \
    "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER DID CACHE R7C' \
    "$CLIENT/lib/lowlevel.c" >/dev/null
grep 'seed_did_cache_from_enumerate' \
    "$CLIENT/lib/did.h" >/dev/null

# Recompile the already-generated tree without running build-native-atp-r1.sh
# again; doing so would intentionally reconstruct lowlevel.c and erase R7C.
# build-rfork-r2.sh still refreshes the ASP overlay, so enable R7B while it
# runs to restore the R7A retry budget and R7B cmdline layer before compiling.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

# Verify all three Finder-reference layers survived the final compile source.
test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' \
    "$CLIENT/lib/asp_transport.c")" -eq 2
grep 'GLOBALTALK FINDER ENUM METADATA R7B' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK FINDER DID CACHE R7C' \
    "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER DID CACHE R7C' \
    "$CLIENT/lib/lowlevel.c" >/dev/null
grep 'seed_did_cache_from_enumerate' \
    "$CLIENT/lib/did.h" >/dev/null

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
    "$ROOT/tools/apply_finder_did_cache_r7c.py"

sh -n "$ROOT/scripts/gt-pull-r7c.sh"

echo
echo "R7C Finder-style DID reuse build ready."
echo "R7B redundant per-file stat removal: retained"
echo "FPEnumerate ParentDirID -> DID cache: enabled"
echo "Active DID cache timeout: sliding refresh"
echo "Child open: parent resolved from DID cache, not repeated full-path walk"
echo "AFP open/read/close commands: unchanged"
echo "R7A ATP timer: unchanged at 2 seconds"
echo "R7A ATP budget: initial request + up to 5 retransmissions"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "R6.1-R6.4 recovery layers: retained as safety/diagnostics"
echo "AFP logical read size: unchanged"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7c.sh 'AFP_URL' 'DEST'"
