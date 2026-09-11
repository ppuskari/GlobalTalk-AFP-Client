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
    echo "  sh scripts/build-filedates-r6-4.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R6.4 persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "Recovery:    short-EOF, metadata, directory boundary, and one remote-EIO retry"
echo "Remote EIO:  file stat/open/read/close and directory stat only"
echo "Local I/O:   never triggers AFP reconnect"
echo

# One process, one normal AFP login/volume attachment, one recursive walk.
# R6.4 adds bounded recovery for generic remote AFP -EIO while retaining all
# prior recovery layers.  Do not restart afpsld between successful files.
exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
