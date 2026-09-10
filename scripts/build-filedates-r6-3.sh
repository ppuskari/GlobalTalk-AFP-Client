#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R6.3 is staged on top of R6.2.  It adds bounded recovery at recursive
# directory boundaries (initial directory stat and whole-directory listing)
# while leaving ATP/ASP and all proven file/resource-fork transport unchanged.
GT_AFP_ENABLE_R6_3=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.3' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

python3 -m py_compile \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_2.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_3.py"

echo
echo "File Dates R6.3 staged persistent recursive build ready."
echo "Native ATP/ASP transport: unchanged from R4"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "R6.1 short-EOF recovery: retained"
echo "R6.2 remote metadata recovery: retained"
echo "Directory stat failure: one classified session recovery"
echo "Directory listing failure/EIO: one bounded recovery"
echo "Failed child recursion: stops and propagates to the parent"
echo
echo "R6.3 is staged for the next diagnostic step."
echo "Prefer R6.2 for the immediate LisaGaming rerun first."
