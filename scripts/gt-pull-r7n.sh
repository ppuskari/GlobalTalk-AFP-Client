#!/bin/bash
set -u

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 {candidate|reference} SERVER_LABEL 'REMOTE_AFP_URL' LOCAL_DIRECTORY" >&2
    exit 2
fi

MODE=$1
SERVER_LABEL=$2
SOURCE=$3
DEST=$4
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PULL="$ROOT/build-r7n-candidate/gt-afp-pull"
LOGDIR="$ROOT/logs"

case "$MODE" in
    candidate) ATP_SENDS=6 ;;
    reference) ATP_SENDS=7 ;;
    *) echo "ERROR: unknown mode: $MODE" >&2; exit 2 ;;
esac

INTERFILE_MS=50

if [ ! -x "$PULL" ]; then
    echo "ERROR: build first with: sh scripts/build-r7n-candidate.sh" >&2
    exit 1
fi

mkdir -p "$DEST" "$LOGDIR"
export GT_AFP_R7K_ATP_SENDS="$ATP_SENDS"
export GT_AFP_R7K_INTERFILE_MS="$INTERFILE_MS"
export GT_AFP_R7M_SKIP_POISON_CLOSE=0

STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$LOGDIR/r7n-${SERVER_LABEL}-${MODE}-${ATP_SENDS}send-${INTERFILE_MS}ms-${STAMP}.log"

{
    echo "GlobalTalk AFP Client R7N"
    echo "Date: $(date)"
    echo "Server label: $SERVER_LABEL"
    echo "Mode: $MODE"
    echo "ATP sends: $ATP_SENDS"
    echo "Pacing ms: $INTERFILE_MS"
    echo "Remote: $SOURCE"
    echo "Local: $DEST"
    echo "Log: $LOG"
    echo
} | tee "$LOG"

if command -v stdbuf >/dev/null 2>&1; then
    stdbuf -oL -eL "$PULL" -r -V -M netatalk "$SOURCE" "$DEST" 2>&1 | tee -a "$LOG"
    RC=${PIPESTATUS[0]}
else
    "$PULL" -r -V -M netatalk "$SOURCE" "$DEST" 2>&1 | tee -a "$LOG"
    RC=${PIPESTATUS[0]}
fi

{
    echo
    echo "gt-afp-pull exit code: $RC"
    echo "Full log saved to: $LOG"
} | tee -a "$LOG"

exit "$RC"
