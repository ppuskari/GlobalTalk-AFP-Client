#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE="$ROOT/build-r7m-latency"
OUT="$ROOT/build-r7n-candidate"

# Reconstruct the exact instrumented R7M/R7L baseline first.
sh "$ROOT/scripts/build-r7m-recovery-latency.sh"

rm -rf "$OUT"
cp -a "$BASE" "$OUT"

PULL="$OUT/gt-afp-pull"
PUSH="$OUT/gt-afp-push"
AFPSLD="$OUT/afpsld"

test -x "$PULL" || {
    echo "ERROR: R7N downloader missing: $PULL" >&2
    exit 1
}
test -x "$PUSH" || {
    echo "ERROR: R7N uploader missing: $PUSH" >&2
    exit 1
}
test -x "$AFPSLD" || {
    echo "ERROR: R7N afpsld missing: $AFPSLD" >&2
    exit 1
}

# Validate emitted/runtime strings, not source-only comment markers.  Every
# guard prints its own diagnostic so set -e cannot make the wrapper disappear
# silently after the nested R7M build.
strings "$PULL" | grep -F 'R7M: stage=best-effort-close' >/dev/null || {
    echo "ERROR: R7M recovery timing marker missing from gt-afp-pull." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7M: stage=recover-session' >/dev/null || {
    echo "ERROR: R7M reconnect timing marker missing from gt-afp-pull." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery-loop marker missing from gt-afp-pull." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict identity marker missing from gt-afp-pull." >&2
    exit 1
}
strings "$AFPSLD" | grep -F 'GT_AFP_R7K_ATP_SENDS' >/dev/null || {
    echo "ERROR: R7K ATP-send runtime control missing from afpsld." >&2
    exit 1
}
strings "$PULL" | grep -F 'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing runtime control missing from gt-afp-pull." >&2
    exit 1
}
strings "$PULL" | grep -F 'GT_AFP_R7M_SKIP_POISON_CLOSE' >/dev/null || {
    echo "ERROR: R7M recovery cleanup runtime control missing from gt-afp-pull." >&2
    exit 1
}

bash -n "$ROOT/scripts/gt-pull-r7n.sh"
bash -n "$ROOT/scripts/gt-roundtrip-r7n.sh"
python3 -m py_compile "$ROOT/tools/summarize_r7m_log.py"
python3 -m py_compile "$ROOT/tools/summarize_r7n_matrix.py"

echo
echo "R7N stability-candidate build ready."
echo "Code baseline: R7M instrumentation over proven R7L recovery"
echo "Candidate transport: 6 total ATP sends / 2-second retry timer"
echo "Candidate pacing: 50 ms"
echo "Preferred compatibility profile: 7 sends / 50 ms"
echo "Normal recovery cleanup: retained"
echo "Recovery budgets: 6 data-fork / 6 metadata cycles"
echo "Resume guard: nonzero matching CNID + exact fork size"
echo "Recovery timing instrumentation: retained"
echo "Reference mode: 7 sends / 50 ms from the same binary"
echo "Round-trip runner: scripts/gt-roundtrip-r7n.sh"
echo "Output: $OUT"
echo "Final R7N candidate binaries: runtime markers verified"
