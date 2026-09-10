#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R6.2 keeps the proven R4/native ATP/session stack, layers R6 and R6.1,
# then adds stage-specific metadata diagnostics and one bounded in-process
# recovery/retry for a failed REMOTE AFP metadata copy.  Local chmod/timestamp
# failures never trigger an AFP reconnect.
GT_AFP_ENABLE_R6_2=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_2.py"

sh -n "$ROOT/scripts/gt-pull-r6.sh"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "File Dates R6.2 persistent recursive build ready."
echo "Native ATP/ASP transport: unchanged from R4"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "Recursive copy model: one persistent AFP login/volume attachment"
echo "Premature EOF: one in-process recovery/retry from offset zero"
echo "Remote metadata failure: one in-process recovery/retry"
echo "Local chmod/timestamp failures: diagnosed, no AFP reconnect"
echo "Failed child recursion: stops and propagates to the parent"
echo "R5 one-process-per-file downloader: not used"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  ./scripts/gt-afp-browser.sh"
