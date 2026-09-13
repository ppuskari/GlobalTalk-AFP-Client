#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "Usage:" >&2
    echo "  $0 {control|patient|paced|combined|balanced|paced25|balanced25} 'REMOTE_AFP_URL' LOCAL_DIRECTORY" >&2
    exit 2
fi

MODE=$1
SOURCE=$2
DEST=$3
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PULL="$ROOT/build-r7k-trials/gt-afp-pull"
VERSION="0.9.5-ddp-native-atp-r7k-finder-trials"

case "$MODE" in
    control)
        ATP_SENDS=6
        INTERFILE_MS=0
        ;;
    patient)
        ATP_SENDS=10
        INTERFILE_MS=0
        ;;
    paced)
        ATP_SENDS=6
        INTERFILE_MS=50
        ;;
    combined)
        ATP_SENDS=10
        INTERFILE_MS=50
        ;;
    balanced)
        # R7K tuning round 2: preserve the successful 50 ms pacing while
        # reducing the maximum inline ATP wait versus the 10-send combined
        # trial.  Eight total sends = initial + seven retransmissions.
        ATP_SENDS=8
        INTERFILE_MS=50
        ;;
    paced25)
        # Test whether half of the successful pacing interval is sufficient
        # while retaining the proven R7A six-send ATP policy.
        ATP_SENDS=6
        INTERFILE_MS=25
        ;;
    balanced25)
        # Middle-ground ATP patience plus reduced think time.
        ATP_SENDS=8
        INTERFILE_MS=25
        ;;
    *)
        echo "ERROR: unknown R7K mode: $MODE" >&2
        echo "Use control, patient, paced, combined, balanced, paced25, or balanced25." >&2
        exit 2
        ;;
esac

if [ ! -x "$PULL" ]; then
    echo "ERROR: R7K downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7k-finder-trials.sh" >&2
    exit 1
fi

strings "$PULL" | grep -F "$VERSION" >/dev/null || {
    echo "ERROR: downloader is not the R7K trial build." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: R7J recovery baseline missing from R7K binary." >&2
    exit 1
}
strings "$PULL" | grep -F 'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing control missing from binary." >&2
    exit 1
}

mkdir -p "$DEST"

export GT_AFP_R7K_ATP_SENDS="$ATP_SENDS"
export GT_AFP_R7K_INTERFILE_MS="$INTERFILE_MS"

echo
echo "R7K Finder-tolerance AFP trial"
echo "Mode:        $MODE"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Binary:      R7K trial markers verified"
echo "Baseline:    R7J full-tree PASS recovery behavior"
echo "ATP timer:   2 seconds"
echo "ATP sends:   $ATP_SENDS total"
echo "Inter-file:  ${INTERFILE_MS} ms after successful metadata"
echo "Recovery:    R7J bounded 6-cycle recovery retained"
echo "Resume:      R7I.2 nonzero CNID + exact-size validation retained"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
