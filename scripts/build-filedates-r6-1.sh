#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R6.1 builds the proven R4/native ATP/session stack, layers R6 persistent
# recursive recovery, then adds premature-EOF recovery and strict recursive
# failure propagation.  ATP/ASP transport remains unchanged.
GT_AFP_ENABLE_R6_1=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py"

sh -n "$ROOT/scripts/gt-pull-r6.sh"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "File Dates R6.1 persistent recursive build ready."
echo "Native ATP/ASP transport: unchanged from R4"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "Recursive copy model: one persistent AFP login/volume attachment"
echo "Premature EOF: one in-process recovery/retry from offset zero"
echo "Explicit session errors: one in-process recovery/retry"
echo "Read/EOF/close/recovery diagnostics: enabled"
echo "Failed child recursion: stops and propagates to the parent"
echo "R5 one-process-per-file downloader: not used"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  ./scripts/gt-afp-browser.sh"
