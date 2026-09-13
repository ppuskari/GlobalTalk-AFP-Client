#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE="$ROOT/build-r7m-latency"
OUT="$ROOT/build-r7n-candidate"

sh "$ROOT/scripts/build-r7m-recovery-latency.sh"

rm -rf "$OUT"
cp -a "$BASE" "$OUT"

PULL="$OUT/gt-afp-pull"

test -x "$PULL" || {
    echo "ERROR: R7N downloader missing: $PULL" >&2
    exit 1
}

strings "$PULL" | grep -F 'GLOBALTALK RECOVERY LATENCY R7M' >/dev/null
strings "$PULL" | grep -F 'R7L: validation stat transient; retrying recovery' >/dev/null
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null
strings "$PULL" | grep -F 'GT_AFP_R7K_ATP_SENDS' >/dev/null
strings "$PULL" | grep -F 'GT_AFP_R7K_INTERFILE_MS' >/dev/null
strings "$PULL" | grep -F 'GT_AFP_R7M_SKIP_POISON_CLOSE' >/dev/null

bash -n "$ROOT/scripts/gt-pull-r7n.sh"
python3 -m py_compile "$ROOT/tools/summarize_r7m_log.py"
python3 -m py_compile "$ROOT/tools/summarize_r7n_matrix.py"

echo
echo "R7N stability-candidate build ready."
echo "Code baseline: R7M instrumentation over proven R7L recovery"
echo "Candidate transport: 6 total ATP sends / 2-second retry timer"
echo "Candidate pacing: 50 ms"
echo "Normal recovery cleanup: retained"
echo "Recovery budgets: 6 data-fork / 6 metadata cycles"
echo "Resume guard: nonzero matching CNID + exact fork size"
echo "Recovery timing instrumentation: retained"
echo "Reference mode: 7 sends / 50 ms from the same binary"
echo "Output: $OUT"
