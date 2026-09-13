#!/bin/bash
set -u

if [ "$#" -ne 3 ]; then
    echo "Usage:" >&2
    echo "  $0 {control|paced|seven50|balanced|paced25|balanced25|patient|combined} 'REMOTE_AFP_URL' LOCAL_DIRECTORY" >&2
    exit 2
fi

MODE=$1
SOURCE=$2
DEST=$3
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PULL="$ROOT/build-r7l-recovery-loop/gt-afp-pull"
LOGDIR="$ROOT/logs"

case "$MODE" in
    control)
        ATP_SENDS=6
        INTERFILE_MS=0
        ;;
    paced)
        ATP_SENDS=6
        INTERFILE_MS=50
        ;;
    seven50)
        ATP_SENDS=7
        INTERFILE_MS=50
        ;;
    balanced)
        ATP_SENDS=8
        INTERFILE_MS=50
        ;;
    paced25)
        ATP_SENDS=6
        INTERFILE_MS=25
        ;;
    balanced25)
        ATP_SENDS=8
        INTERFILE_MS=25
        ;;
    patient)
        ATP_SENDS=10
        INTERFILE_MS=0
        ;;
    combined)
        ATP_SENDS=10
        INTERFILE_MS=50
        ;;
    *)
        echo "ERROR: unknown R7L trial mode: $MODE" >&2
        exit 2
        ;;
esac

if [ ! -x "$PULL" ]; then
    echo "ERROR: R7L downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7l-recovery-loop.sh" >&2
    exit 1
fi

strings "$PULL" | grep -F \
    'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: downloader is not the R7L recovery-loop build." >&2
    exit 1
}
strings "$PULL" | grep -F \
    'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict identity guard missing." >&2
    exit 1
}
strings "$PULL" | grep -F \
    'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: R7J metadata recovery baseline missing." >&2
    exit 1
}

mkdir -p "$DEST" "$LOGDIR"

export GT_AFP_R7K_ATP_SENDS="$ATP_SENDS"
export GT_AFP_R7K_INTERFILE_MS="$INTERFILE_MS"

STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$LOGDIR/r7l-${MODE}-${ATP_SENDS}send-${INTERFILE_MS}ms-${STAMP}.log"

{
    echo "============================================================"
    echo "GlobalTalk AFP Client R7L recovery-loop trial"
    echo "Date:        $(date)"
    echo "Mode:        $MODE"
    echo "ATP timer:   2 seconds"
    echo "ATP sends:   $ATP_SENDS total"
    echo "Inter-file:  $INTERFILE_MS ms after successful metadata"
    echo "Recovery:    R7L whole-stage bounded retry, 6 cycles"
    echo "Identity:    R7I.2 nonzero CNID + exact fork size"
    echo "Remote base: $SOURCE"
    echo "Local base:  $DEST"
    echo "Log file:    $LOG"
    echo "============================================================"
    echo
} | tee "$LOG"

# This pipeline runs inside this child Bash script, not in the user's login
# shell. PIPESTATUS therefore preserves gt-afp-pull's real exit status while
# tee captures stdout+stderr. Exiting this script simply returns to PuTTY.
set +e
"$PULL" -r -V -M netatalk "$SOURCE" "$DEST" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
set -e

{
    echo
    echo "============================================================"
    echo "gt-afp-pull exit code: $RC"
    echo "Full log saved to: $LOG"
    echo "============================================================"
} | tee -a "$LOG"

exit "$RC"
