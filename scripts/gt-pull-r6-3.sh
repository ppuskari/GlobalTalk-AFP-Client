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
    echo "  sh scripts/build-filedates-r6-3.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R6.3 staged persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "Recovery:    R6.1 file + R6.2 metadata + R6.3 directory boundary"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
