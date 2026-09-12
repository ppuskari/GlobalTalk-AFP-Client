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
    echo "ERROR: downloader not found; build R7FC first" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R7FC diagnostic: R7FB + FinderInfo FPEnumerate field"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Xattrs:      generic stage skipped"
echo "Enumeration: data length + resource length + FinderInfo"
echo "Reuse:       added fields carried only, NOT consumed"
echo "Recovery:    unchanged R7D behavior"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
