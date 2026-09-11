#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R6.4 keeps the proven R4/native ATP/session stack and all R6.x recovery
# layers, then treats generic remote AFP -EIO from file stat/open/read/close
# as one bounded session-integrity event.  Local filesystem EIO remains local.
GT_AFP_ENABLE_R6_4=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.3' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_2.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_3.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_4.py"

sh -n "$ROOT/scripts/gt-pull-r6-4.sh"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "File Dates R6.4 persistent recursive build ready."
echo "Native ATP/ASP transport: unchanged from R4"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "R6.1 premature-EOF recovery: retained"
echo "R6.2 remote metadata recovery: retained"
echo "R6.3 directory-boundary recovery: retained"
echo "Remote file stat/open/read/close EIO: one bounded recovery"
echo "Directory stat EIO: one bounded recovery"
echo "Local filesystem failures: never trigger AFP reconnect"
echo "Failed child recursion: stops and propagates to the parent"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r6-4.sh 'AFP_URL' 'DEST'"
