#!/bin/bash
set -u

if [ "$#" -ne 3 ]; then
    echo "Usage:" >&2
    echo "  $0 {timed|fastclose} 'REMOTE_AFP_URL' LOCAL_DIRECTORY" >&2
    exit 2
fi

MODE=$1
SOURCE=$2
DEST=$3
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PULL="$ROOT/build-r7m-latency/gt-afp-pull"
LOGDIR="$ROOT/logs"
ATP_SENDS=7
INTERFILE_MS=50

case "$MODE" in
    timed)
        SKIP_POISON_CLOSE=0
        ;;
    fastclose)
        SKIP_POISON_CLOSE=1
        ;;
    *)
        echo "ERROR: unknown R7M mode: $MODE" >&2
        exit 2
        ;;
esac

if [ ! -x "$PULL" ]; then
    echo "ERROR: R7M downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7m-recovery-latency.sh" >&2
    exit 1
fi

strings "$PULL" | grep -F \
    'GT_AFP_R7M_SKIP_POISON_CLOSE' >/dev/null || {
    echo "ERROR: downloader is not the R7M latency build." >&2
    exit 1
}
strings "$PULL" | grep -F \
    'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery-loop baseline missing." >&2
    exit 1
}
strings "$PULL" | grep -F \
    'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict identity guard missing." >&2
    exit 1
}

mkdir -p "$DEST" "$LOGDIR"

export GT_AFP_R7K_ATP_SENDS="$ATP_SENDS"
export GT_AFP_R7K_INTERFILE_MS="$INTERFILE_MS"
export GT_AFP_R7M_SKIP_POISON_CLOSE="$SKIP_POISON_CLOSE"

STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$LOGDIR/r7m-${MODE}-${ATP_SENDS}send-${INTERFILE_MS}ms-${STAMP}.log"

{
    echo "============================================================"
    echo "GlobalTalk AFP Client R7M recovery-latency trial"
    echo "Date:              $(date)"
    echo "Mode:              $MODE"
    echo "ATP timer:         2 seconds"
    echo "ATP sends:         $ATP_SENDS total"
    echo "Inter-file pacing: $INTERFILE_MS ms"
    echo "Skip poison close: $SKIP_POISON_CLOSE"
    echo "Recovery:          R7L bounded six-cycle state machine"
    echo "Identity:          R7I.2 nonzero CNID + exact fork size"
    echo "Remote base:       $SOURCE"
    echo "Local base:        $DEST"
    echo "Log file:          $LOG"
    echo "============================================================"
    echo
} | tee "$LOG"

set +e
if command -v stdbuf >/dev/null 2>&1; then
    stdbuf -oL -eL "$PULL" -r -V -M netatalk "$SOURCE" "$DEST" \
        2>&1 | tee -a "$LOG"
    RC=${PIPESTATUS[0]}
else
    "$PULL" -r -V -M netatalk "$SOURCE" "$DEST" \
        2>&1 | tee -a "$LOG"
    RC=${PIPESTATUS[0]}
fi
set -e

{
    echo
    echo "============================================================"
    echo "gt-afp-pull exit code: $RC"
    echo "Full log saved to: $LOG"
    echo "============================================================"
} | tee -a "$LOG"

exit "$RC"
