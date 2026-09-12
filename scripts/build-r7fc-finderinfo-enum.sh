#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7fc-finderinfo-enum"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7fc.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

sh "$ROOT/scripts/build-r7e-zero-datafork.sh"
python3 "$ROOT/tools/apply_diag_r7fa_xattr_skip.py" "$CLIENT"
python3 "$ROOT/tools/apply_diag_r7fb_rsrc_enum.py" "$CLIENT"
python3 "$ROOT/tools/apply_diag_r7fc_finderinfo_enum.py" "$CLIENT"

grep 'GLOBALTALK R7FA XATTR SKIP DIAGNOSTIC' \
    "$CLIENT/daemon/metadata.c" >/dev/null
grep 'GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC' \
    "$CLIENT/include/afpsl.h" >/dev/null
grep 'GLOBALTALK R7FC FINDERINFO ENUM DIAGNOSTIC' \
    "$CLIENT/include/afpsl.h" >/dev/null
grep 'filebitmap |= kFPFinderInfoBit' \
    "$CLIENT/lib/lowlevel.c" >/dev/null

python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

grep 'GLOBALTALK R7FC FINDERINFO ENUM DIAGNOSTIC' \
    "$CLIENT/include/afpsl.h" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_diag_r7fa_xattr_skip.py" \
    "$ROOT/tools/apply_diag_r7fb_rsrc_enum.py" \
    "$ROOT/tools/apply_diag_r7fc_finderinfo_enum.py"
sh -n "$ROOT/scripts/gt-pull-r7fc.sh"

echo
echo "R7FC FinderInfo enumeration diagnostic build ready."
echo "Base: R7E"
echo "R7FA generic xattr suppression: retained"
echo "R7FB resource-length field: retained"
echo "FPEnumerate: additionally requests FinderInfo"
echo "Resource length/FinderInfo: carried but NOT reused"
echo "Legacy FinderInfo/resource metadata queries: unchanged"
echo "Recovery/timers/read sizes: unchanged"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7fc.sh 'AFP_URL' 'DEST'"
