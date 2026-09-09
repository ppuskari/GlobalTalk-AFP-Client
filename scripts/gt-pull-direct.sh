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
    echo >&2
    echo "Build first:" >&2
    echo "  sh scripts/build-native-atp-r1.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

pkill -u "$USER" -x afpsld 2>/dev/null || true
sleep 1

echo
echo "Remote:"
echo "  $SOURCE"
echo
echo "Direct destination:"
echo "  $DEST"
echo

"$PULL" \
    -r \
    -V \
    -M netatalk \
    "$SOURCE" \
    "$DEST"

echo
echo "Download complete."
echo "Files landed directly in:"
echo "  $DEST"
