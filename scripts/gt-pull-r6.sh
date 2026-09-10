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
    echo "  sh scripts/build-filedates-r6.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R6 persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "Recovery:    in-process, only on recoverable AFP session errors"
echo

# One process, one normal AFP login/volume attachment, one recursive walk.
# The R6-patched cmdline client performs session recovery internally when a
# recoverable operation fails.  Do not restart afpsld between successful files.
exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
