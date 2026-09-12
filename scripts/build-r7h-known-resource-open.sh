#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7h-known-resource-open"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7h.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

sh "$ROOT/scripts/build-r7g-known-data-open.sh"
python3 "$ROOT/tools/apply_known_resource_open_r7h.py" "$CLIENT"

grep 'GLOBALTALK KNOWN DATA OPEN R7G PIN095' "$CLIENT/lib/midlevel.c" >/dev/null
grep 'GLOBALTALK KNOWN RESOURCE OPEN R7H' "$CLIENT/lib/resource.c" >/dev/null
grep 'ml_open_resourcefork_known' "$CLIENT/lib/midlevel.c" >/dev/null
grep 'afp_sl_open_resourcefork_known' "$CLIENT/daemon/stateless.c" >/dev/null
grep 'afp_sl_open_resourcefork_known' "$CLIENT/daemon/metadata.c" >/dev/null

python3 "$ROOT/tools/prepare_native_atp_jessie.py" "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

grep 'GLOBALTALK FINDER RECOVERY DID R7D' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' "$CLIENT/include/afpsl.h" >/dev/null
grep 'GLOBALTALK KNOWN DATA OPEN R7G PIN095' "$CLIENT/lib/midlevel.c" >/dev/null
grep 'GLOBALTALK KNOWN RESOURCE OPEN R7H' "$CLIENT/lib/resource.c" >/dev/null
test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' "$CLIENT/lib/asp_transport.c")" -eq 2

for binary in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta
do
    strings "$OUT/$binary" | grep 'GLOBALTALK NATIVE ATP R1' >/dev/null || {
        echo "ERROR: native ATP marker missing from $binary" >&2
        exit 1
    }
done

python3 -m py_compile \
    "$ROOT/tools/apply_known_data_open_r7g.py" \
    "$ROOT/tools/apply_known_data_open_r7g_pin095.py" \
    "$ROOT/tools/apply_known_resource_open_r7h.py"

sh -n "$ROOT/scripts/gt-pull-r7h.sh"

echo
echo "R7H known-resource-open build ready."
echo "Pinned Netatalk Client 0.9.5 API: verified"
echo "R7G known-size data open: retained"
echo "R4 stateful resource fork: retained"
echo "Resource-fork open: AFP2 pre-open parameter query skipped"
echo "Resource size source: R7F enumeration or fresh post-recovery query"
echo "Resource read/close semantics: unchanged"
echo "R7E zero-data-fork skip: retained"
echo "R7D recovery DID rebuild: retained"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7h.sh 'AFP_URL' 'DEST'"
