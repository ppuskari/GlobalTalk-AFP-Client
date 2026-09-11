#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R7A is the first Finder-reference build.  Keep the entire proven R4/R6.4
# stack, but match the System 7.6 Finder capture's observed ATP command retry
# budget: initial TREQ plus as many as five 2-second retransmissions.
GT_AFP_ENABLE_R7A=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' \
    "$CLIENT/lib/asp_transport.c")" -eq 2

test "$(grep -c 'atpb.atp_sreqtries = 6;' \
    "$CLIENT/lib/asp_transport.c")" -eq 2

python3 -m py_compile \
    "$ROOT/tools/apply_finder_atp_retry_r7a.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_2.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_3.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_4.py"

sh -n "$ROOT/scripts/gt-pull-r7a.sh"

echo
echo "R7A Finder-compatible ATP retry build ready."
echo "System 7.6 reference capture: initial request + 5 retries observed"
echo "ASP request timeout: unchanged at 2 seconds"
echo "ASP command/write send budget: 6 total sends"
echo "Selective ATP bitmap retransmission: unchanged"
echo "ATP TID/XO/TREL handling: unchanged"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "R6.1-R6.4 recovery layers: retained for diagnostics/safety"
echo "AFP logical read size: unchanged in R7A"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7a.sh 'AFP_URL' 'DEST'"
