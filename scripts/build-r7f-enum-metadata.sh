#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7f-enum-metadata"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7f.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# Generate and validate the complete R7E tree first.
sh "$ROOT/scripts/build-r7e-zero-datafork.sh"

# Layer richer FPEnumerate metadata and reuse it only on the healthy path.
python3 "$ROOT/tools/apply_enumerated_metadata_r7f.py" "$CLIENT"

grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' \
    "$CLIENT/include/afpsl.h" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' \
    "$CLIENT/lib/lowlevel.c" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' \
    "$CLIENT/daemon/metadata.c" >/dev/null
grep 'copy_remote_metadata_to_local_r7f' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ENUMERATED METADATA R7F' \
    "$CLIENT/include/afpsl.h" >/dev/null
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
    "$ROOT/tools/apply_zero_datafork_skip_r7e.py" \
    "$ROOT/tools/apply_enumerated_metadata_r7f.py"

sh -n "$ROOT/scripts/gt-pull-r7f.sh"

echo
echo "R7F enumerated-metadata build ready."
echo "R7E zero-data-fork skip: retained"
echo "FPEnumerate: FinderInfo + data/resource lengths carried forward"
echo "Healthy recursive file metadata: no extra FinderInfo/rsrc-size query"
echo "AFP < 3.2: generic xattr enumeration skipped"
echo "Post-recovery metadata: fresh legacy lookup"
echo "R7D recovery DID rebuild: retained"
echo "R7A ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo "R4 stateful resource-fork stream: retained"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7f.sh 'AFP_URL' 'DEST'"
