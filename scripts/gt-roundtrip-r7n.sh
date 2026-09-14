#!/bin/bash
set -u

if [ "$#" -ne 4 ]; then
    echo "Usage:" >&2
    echo "  $0 SERVER_LABEL 'SOURCE_AFP_URL' 'DEST_PARENT_AFP_URL' LOCAL_STAGE_PARENT" >&2
    echo >&2
    echo "Runs a non-destructive 7-send/50-ms AFP round trip:" >&2
    echo "  AFP source -> unique local staging tree -> AFP destination parent" >&2
    echo >&2
    echo "The destination AFP directory must already exist and must not be" >&2
    echo "inside the source tree." >&2
    exit 2
fi

SERVER_LABEL=$1
SOURCE=$2
DEST_PARENT=$3
STAGE_PARENT=$4
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD="$ROOT/build-r7n-candidate"
PULL="$BUILD/gt-afp-pull"
PUSH="$BUILD/gt-afp-push"
RESET="$ROOT/scripts/gt-afp-reset.sh"
LOGDIR="$ROOT/logs"
ATP_SENDS=7
INTERFILE_MS=50

if [ ! -x "$PULL" ]; then
    echo "ERROR: R7N pull client missing: $PULL" >&2
    echo "Build first with: sh scripts/build-r7n-candidate.sh" >&2
    exit 1
fi
if [ ! -x "$PUSH" ]; then
    echo "ERROR: R7N push client missing: $PUSH" >&2
    echo "Build first with: sh scripts/build-r7n-candidate.sh" >&2
    exit 1
fi
if [ ! -x "$RESET" ]; then
    echo "ERROR: reset helper missing: $RESET" >&2
    exit 1
fi
if [ "$SOURCE" = "$DEST_PARENT" ]; then
    echo "ERROR: source and destination AFP URLs are identical." >&2
    exit 1
fi

mkdir -p "$STAGE_PARENT" "$LOGDIR"

STAMP=$(date +%Y%m%d-%H%M%S)
SAFE_LABEL=$(printf '%s' "$SERVER_LABEL" | tr -c 'A-Za-z0-9._-' '_')
STAGE="$STAGE_PARENT/r7n-roundtrip-${SAFE_LABEL}-${STAMP}"
PULL_LOG="$LOGDIR/r7n-${SAFE_LABEL}-roundtrip-pull-7send-50ms-${STAMP}.log"
PUSH_LOG="$LOGDIR/r7n-${SAFE_LABEL}-roundtrip-push-7send-50ms-${STAMP}.log"
SUMMARY_LOG="$LOGDIR/r7n-${SAFE_LABEL}-roundtrip-summary-${STAMP}.log"

mkdir -p "$STAGE"

export GT_AFP_R7K_ATP_SENDS="$ATP_SENDS"
export GT_AFP_R7K_INTERFILE_MS="$INTERFILE_MS"
export GT_AFP_R7M_SKIP_POISON_CLOSE=0

{
    echo "GlobalTalk AFP Client R7N local round-trip"
    echo "Date: $(date)"
    echo "Server label: $SERVER_LABEL"
    echo "ATP sends: $ATP_SENDS"
    echo "ATP retry timer: 2 seconds"
    echo "Post-object pacing: $INTERFILE_MS ms"
    echo "Source AFP URL: $SOURCE"
    echo "Destination parent AFP URL: $DEST_PARENT"
    echo "Local staging tree: $STAGE"
    echo "Pull log: $PULL_LOG"
    echo "Push log: $PUSH_LOG"
    echo
} | tee "$SUMMARY_LOG"

"$RESET"

{
    echo "============================================================"
    echo "R7N ROUND TRIP - PULL LEG"
    echo "Source: $SOURCE"
    echo "Local:  $STAGE"
    echo "============================================================"
} | tee "$PULL_LOG"

set +e
if command -v stdbuf >/dev/null 2>&1; then
    stdbuf -oL -eL "$PULL" -r -V -M netatalk "$SOURCE" "$STAGE" 2>&1 | tee -a "$PULL_LOG"
    PULL_RC=${PIPESTATUS[0]}
else
    "$PULL" -r -V -M netatalk "$SOURCE" "$STAGE" 2>&1 | tee -a "$PULL_LOG"
    PULL_RC=${PIPESTATUS[0]}
fi
set -e

echo "Pull exit code: $PULL_RC" | tee -a "$PULL_LOG" "$SUMMARY_LOG"

if [ "$PULL_RC" -ne 0 ]; then
    echo "ERROR: pull leg failed; push leg was not attempted." | tee -a "$SUMMARY_LOG" >&2
    echo "Local staging tree retained at: $STAGE" | tee -a "$SUMMARY_LOG"
    exit "$PULL_RC"
fi

FILE_COUNT=$(find "$STAGE" -type f -print 2>/dev/null | wc -l | tr -d ' ')
DIR_COUNT=$(find "$STAGE" -type d -print 2>/dev/null | wc -l | tr -d ' ')
BYTE_COUNT=$(find "$STAGE" -type f -printf '%s\n' 2>/dev/null | awk '{s += $1} END {printf "%.0f", s + 0}')

echo "Local staging files: $FILE_COUNT" | tee -a "$SUMMARY_LOG"
echo "Local staging directories: $DIR_COUNT" | tee -a "$SUMMARY_LOG"
echo "Local staging data-fork bytes: $BYTE_COUNT" | tee -a "$SUMMARY_LOG"

# afpsld inherits retry/pacing environment at process start.  Reset between
# legs so the push gets a fresh session and cannot reuse pull-side state.
"$RESET"

{
    echo "============================================================"
    echo "R7N ROUND TRIP - PUSH LEG"
    echo "Local:       $STAGE"
    echo "Destination: $DEST_PARENT"
    echo "============================================================"
} | tee "$PUSH_LOG"

set +e
if command -v stdbuf >/dev/null 2>&1; then
    stdbuf -oL -eL "$PUSH" -r -V -M netatalk "$STAGE" "$DEST_PARENT" 2>&1 | tee -a "$PUSH_LOG"
    PUSH_RC=${PIPESTATUS[0]}
else
    "$PUSH" -r -V -M netatalk "$STAGE" "$DEST_PARENT" 2>&1 | tee -a "$PUSH_LOG"
    PUSH_RC=${PIPESTATUS[0]}
fi
set -e

echo "Push exit code: $PUSH_RC" | tee -a "$PUSH_LOG" "$SUMMARY_LOG"

{
    echo
    echo "Round-trip summary"
    echo "  pull rc: $PULL_RC"
    echo "  push rc: $PUSH_RC"
    echo "  local files: $FILE_COUNT"
    echo "  local dirs: $DIR_COUNT"
    echo "  local data-fork bytes: $BYTE_COUNT"
    echo "  staging retained: $STAGE"
    echo "  pull log: $PULL_LOG"
    echo "  push log: $PUSH_LOG"
    echo "  summary: $SUMMARY_LOG"
} | tee -a "$SUMMARY_LOG"

exit "$PUSH_RC"
