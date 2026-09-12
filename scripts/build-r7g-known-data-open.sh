#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7g-known-data-open"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7g.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

sh "$ROOT/scripts/build-r7f-enum-metadata.sh"
python3 "$ROOT/tools/apply_known_data_open_r7g.py" "$CLIENT"
python3 "$ROOT/tools/apply_known_data_open_r7g_pin095.py" "$CLIENT"

grep 'GLOBALTALK ENUMERATED METADATA R7F' "$CLIENT/include/afpsl.h" >/dev/null
grep 'GLOBALTALK KNOWN DATA OPEN R7G' "$CLIENT/include/afp.h" >/dev/null
grep 'GLOBALTALK KNOWN DATA OPEN R7G' "$CLIENT/lib/lowlevel.c" >/dev/null
grep 'GLOBALTALK KNOWN DATA OPEN R7G PIN095' "$CLIENT/lib/midlevel.c" >/dev/null
grep 'afp_sl_open_known_data' "$CLIENT/daemon/stateless.c" >/dev/null
grep 'afp_sl_open_known_data' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 "$ROOT/tools/prepare_native_atp_jessie.py" "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' "$CLIENT/include/afpsl.h" >/dev/null
grep 'GLOBALTALK KNOWN DATA OPEN R7G PIN095' "$CLIENT/lib/midlevel.c" >/dev/null
test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' "$CLIENT/lib/asp_transport.c")" -eq 2

for binary in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta
do
    strings "$OUT/$binary" | grep 'GLOBALTALK NATIVE ATP R1' >/dev/null || {
        echo "ERROR: native ATP marker missing from $binary" >&2
        exit 1
    }
done

python3 -m py_compile \
    "$ROOT/tools/apply_enumerated_metadata_r7f.py" \
    "$ROOT/tools/apply_known_data_open_r7g.py" \
    "$ROOT/tools/apply_known_data_open_r7g_pin095.py"

sh -n "$ROOT/scripts/gt-pull-r7g.sh"

echo
echo "R7G known-data-open build ready."
echo "Pinned Netatalk Client 0.9.5 API: verified"
echo "R7F rich enumeration metadata: retained"
echo "Healthy nonzero data forks: AFP2 pre-open parameter query skipped"
echo "FPOpenFork/read/close: unchanged"
echo "Post-recovery data open: conservative normal path"
echo "R7E zero-data-fork skip: retained"
echo "R7D recovery DID rebuild: retained"
echo "Resource-fork open path: unchanged"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7g.sh 'AFP_URL' 'DEST'"
