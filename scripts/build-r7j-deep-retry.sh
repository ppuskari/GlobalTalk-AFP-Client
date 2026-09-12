#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r7j-deep-retry"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7j.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# First reconstruct and verify the complete R7I.2 source stack.
sh "$ROOT/scripts/build-r7i-resume-datafork.sh"

# R7J changes recovery-only policy after R7I.2 is fully applied.
python3 "$ROOT/tools/apply_deep_recovery_r7j.py" "$CLIENT"

grep 'GLOBALTALK DEEP RECOVERY R7J' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'const int max_recoveries = 6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'failed DID-prime never proceeds directly to metadata' \
    "$ROOT/tools/apply_deep_recovery_r7j.py" >/dev/null

# Recompile the already-generated R7I.2+R7J source without reconstructing it.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

GT_AFP_ENABLE_R7B=1 \
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

# Verify the proven stack plus R7J survived the final compile.
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME DATAFORK R7I' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME IDENTITY R7I.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DEEP RECOVERY R7J' \
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

strings "$OUT/gt-afp-pull" | grep -F "$VERSION" >/dev/null || {
    echo "ERROR: final gt-afp-pull is not the R7J version." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: R7J metadata recovery loop missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7J: metadata recovery DID-prime' >/dev/null || {
    echo "ERROR: R7J DID-prime gate missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: strict R7I.2 identity validation missing." >&2
    exit 1
}

python3 -m py_compile \
    "$ROOT/tools/apply_deep_recovery_r7j.py"
sh -n "$ROOT/scripts/gt-pull-r7j.sh"

echo
echo "R7J deep-recovery build ready."
echo "Base: proven R7I.2/R7E healthy path retained"
echo "Normal AFP no-error path: unchanged"
echo "Data-fork in-process recovery budget: 6"
echo "Metadata/session recovery budget: 6"
echo "Recovery-only settle delay: 1 second after reconnect/failed prime"
echo "Metadata retry requires successful R7D DID-prime"
echo "Failed reconnect/DID-prime consumes budget and retries"
echo "R7I.2 CNID + exact-size resume validation retained"
echo "ATP timer: unchanged at 2 seconds"
echo "ATP transaction budget: unchanged at initial + 5 retransmissions"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "Healthy-path AFP request count: unchanged"
echo "Final gt-afp-pull binary: R7J markers verified"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7j.sh 'AFP_URL' 'DEST'"
