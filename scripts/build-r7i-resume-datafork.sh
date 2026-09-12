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

# Replace only the data-fork recovery path. No healthy-path AFP operations,
# ATP timing, enumeration layout, metadata behavior, or resource-fork behavior
# are changed by R7I.
python3 "$ROOT/tools/apply_resume_datafork_r7i.py" "$CLIENT"

# AFP 2.x reconnects can legitimately report a shifted mtime because the new
# session recalculates the server clock offset. Use AFP NodeID/CNID + fork size
# for resume identity instead; keep mtime drift as a diagnostic only.
python3 "$ROOT/tools/apply_resume_identity_r7i1.py" "$CLIENT"

grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME DATAFORK R7I' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME IDENTITY R7I.1' \
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

# Final generated source must retain the full proven stack plus R7I/R7I.1.
grep 'GLOBALTALK FINDER DID CACHE R7C' "$CLIENT/lib/did.c" >/dev/null
grep 'GLOBALTALK FINDER RECOVERY DID R7D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK ZERO DATAFORK SKIP R7E' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME DATAFORK R7I' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME IDENTITY R7I.1' \
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

# R7I uses the same output directory as R7E. Do not allow a stale R7E
# executable to masquerade as an R7I build if any compile/layer step regresses.
strings "$OUT/gt-afp-pull" | grep -F "$VERSION" >/dev/null || {
    echo "ERROR: final gt-afp-pull is not the R7I version." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7I: recovery requested' >/dev/null || {
    echo "ERROR: R7I recovery code missing from final gt-afp-pull." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7I: resume validation passed' >/dev/null || {
    echo "ERROR: R7I resume validation missing from final gt-afp-pull." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7I: resuming current file' >/dev/null || {
    echo "ERROR: R7I resume loop missing from final gt-afp-pull." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F 'R7I.1: resume mtime drift ignored' >/dev/null || {
    echo "ERROR: R7I.1 CNID/size identity validation missing." >&2
    exit 1
}

python3 -m py_compile \
    "$ROOT/tools/apply_resume_datafork_r7i.py" \
    "$ROOT/tools/apply_resume_identity_r7i1.py"
sh -n "$ROOT/scripts/gt-pull-r7i.sh"

echo
echo "R7I resumable data-fork recovery build ready."
echo "Base: virgin R7E behavior retained"
echo "Normal no-error path: unchanged"
echo "Recovery: preserve last successfully written byte offset"
echo "Recovery identity: AFP NodeID/CNID + exact data-fork size"
echo "AFP2 reconnect mtime drift: diagnostic only, not fatal"
echo "Recovery DID rebuild: retained"
echo "Per-file in-process recovery budget: 3"
echo "Known empty data forks: R7E skip retained"
echo "ATP timer/budget: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "AFP logical read size: unchanged"
echo "Metadata/resource-fork paths: unchanged"
echo "Final gt-afp-pull binary: R7I/R7I.1 markers verified"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7i.sh 'AFP_URL' 'DEST'"
