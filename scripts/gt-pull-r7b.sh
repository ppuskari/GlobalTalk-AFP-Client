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
    echo "  sh scripts/build-r7b-finder-enum.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R7B Finder-style persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "Traversal:   reuse FPEnumerate metadata; no redundant per-file stat"
echo "ATP timer:   2 seconds"
echo "ATP budget:  initial request + up to 5 retransmissions"
echo "Recovery:    R6.4 safety net retained"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
