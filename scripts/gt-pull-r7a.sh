#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage:" >&2
    echo "  $0 'REMOTE_AFP_URL' LOCAL_DIRECTORY" >&2
    exit 2
fi

SOURCE=$1
DEST=$2
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PULL="$ROOT/build-native-atp-r1/gt-afp-pull"

if [ ! -x "$PULL" ]; then
    echo "ERROR: downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7a-finder-atp.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R7A Finder-reference persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "ATP timer:   2 seconds (matches System 7.6 capture)"
echo "ATP budget:  initial request + up to 5 retransmissions"
echo "ATP retry:   same TID with selective missing-response bitmap"
echo "Recovery:    R6.4 safety net retained"
echo

# R7A changes only the ordinary ASP ATP retry budget to match behavior observed
# in the successful System 7.6 Finder capture.  The native ATP engine, AFP read
# size, response ceiling, resource-fork path, and R6.4 safety net are otherwise
# unchanged.
exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
