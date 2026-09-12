#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7fa-xattr-skip"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7fa.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# Proven baseline first.
sh "$ROOT/scripts/build-r7e-zero-datafork.sh"

# One diagnostic variable only.
python3 "$ROOT/tools/apply_diag_r7fa_xattr_skip.py" "$CLIENT"

grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK R7FA XATTR SKIP DIAGNOSTIC' \
    "$CLIENT/daemon/metadata.c" >/dev/null

python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

grep 'GLOBALTALK R7FA XATTR SKIP DIAGNOSTIC' \
    "$CLIENT/daemon/metadata.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_diag_r7fa_xattr_skip.py"
sh -n "$ROOT/scripts/gt-pull-r7fa.sh"

echo
echo "R7FA xattr-skip diagnostic build ready."
echo "Base: R7E proven zero-data-fork build"
echo "FPEnumerate payload: unchanged from R7E"
echo "FinderInfo lookup: unchanged"
echo "Resource-size lookup/stream: unchanged"
echo "Generic remote xattr list/get stage: skipped"
echo "R7D recovery DID rebuild: retained"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7fa.sh 'AFP_URL' 'DEST'"
