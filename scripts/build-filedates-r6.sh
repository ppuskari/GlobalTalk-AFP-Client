#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R6 keeps the entire proven R4 date/native ATP/session stack and layers only
# persistent recursive AFP recovery in cmdline_afp.c.  The environment flag is
# consumed by apply_batch_integrity_r2.py during the normal native build, before
# compilation, so no transport source is replaced.
GT_AFP_ENABLE_R6=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

grep 'GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py"

sh -n "$ROOT/scripts/gt-pull-r6.sh"

echo
echo "File Dates R6 persistent recursive build ready."
echo "Native ATP/ASP transport: unchanged from R4"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "Recursive copy model: one persistent AFP login/volume attachment"
echo "Directory page recovery: in-process"
echo "File read/open/stat/close recovery: in-process, retry from offset zero"
echo "Metadata recovery: in-process"
echo "R5 one-process-per-file downloader: not used by R6"
echo
echo "Run:"
echo "  ./scripts/gt-afp-browser.sh"
