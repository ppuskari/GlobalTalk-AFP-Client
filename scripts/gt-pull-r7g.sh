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
    echo "  sh scripts/build-r7g-known-data-open.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "R7G Finder-style persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Session:     one login/attach for the recursive walk"
echo "Traversal:   R7C ParentDirID/DID reuse"
echo "Metadata:    R7F rich FPEnumerate reuse"
echo "Data open:   known-size AFP2 open skips pre-open parameter query"
echo "Recovery:    R7D DID rebuild; conservative open after recovery"
echo "Empty forks: R7E known zero-byte data-fork skip retained"
echo "ATP timer:   2 seconds"
echo "ATP budget:  initial request + up to 5 retransmissions"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
