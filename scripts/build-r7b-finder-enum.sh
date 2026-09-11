#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"

# R7B keeps the full R7A/R6.4 stack but removes the redundant per-file stat
# issued immediately after FPEnumerate/direct pre-stat metadata is already
# available.  This is a Finder-style traversal change above AFP transport.
GT_AFP_ENABLE_R7B=1 \
    sh "$ROOT/scripts/build-filedates-r4.sh"

grep 'GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

test "$(grep -c 'GLOBALTALK FINDER ATP RETRY R7A' \
    "$CLIENT/lib/asp_transport.c")" -eq 2

grep 'GLOBALTALK FINDER ENUM METADATA R7B' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

if grep 'op_ret = afp_sl_stat(&vol_id, path, NULL, stat);' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null 2>&1; then
    echo "ERROR: R7B redundant retrieve_file stat still present." >&2
    exit 1
fi

python3 -m py_compile \
    "$ROOT/tools/apply_finder_atp_retry_r7a.py" \
    "$ROOT/tools/apply_finder_enum_metadata_r7b.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_1.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_2.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_3.py" \
    "$ROOT/tools/apply_persistent_recursive_recovery_r6_4.py"

sh -n "$ROOT/scripts/gt-pull-r7b.sh"

echo
echo "R7B Finder-style enumeration metadata build ready."
echo "Per-file redundant AFP stat: removed"
echo "Recursive file size/mode/time: reused from FPEnumerate"
echo "Direct get metadata: reused from caller's initial stat"
echo "File open/read/close path: unchanged"
echo "Open ENOENT: explicitly diagnosed as enumerate/path mismatch"
echo "R7A ATP 2-second timer + initial/5-retry budget: retained"
echo "ATP response ceiling: unchanged (8 x 578 = 4624 bytes)"
echo "R4 resource-fork stream: retained"
echo "R6.1-R6.4 recovery layers: retained as safety/diagnostics"
echo
echo "Run:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  sh scripts/gt-pull-r7b.sh 'AFP_URL' 'DEST'"
