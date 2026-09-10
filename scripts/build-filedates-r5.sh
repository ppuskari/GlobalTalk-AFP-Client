#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Build the proven R4 date/transport stack first.  R5 deliberately adds no
# ATP/ASP protocol changes; it adds checkpointed recursive recovery above the
# existing single-file pull path.
sh "$ROOT/scripts/build-filedates-r4.sh"

python3 -m py_compile "$ROOT/scripts/gt-pull-resilient.py"

echo
echo "File Dates R5 resilient download build ready."
echo "Native ATP/session transport: unchanged from R4"
echo "Classic Finder date compatibility: unchanged from R4"
echo "Recursive downloader: checkpointed per-file R5"
echo "  file/list failures get a fresh-session retry"
echo "  persistent bad objects are reported and traversal continues"
echo "  no whole-subtree restart is required"
echo
echo "Optional tuning:"
echo "  GT_AFP_R5_FILE_ATTEMPTS=2   (default)"
echo "  GT_AFP_R5_LIST_ATTEMPTS=2   (default)"
echo "  GT_AFP_R5_ROTATE_EVERY=0    (0 disables proactive rotation)"
