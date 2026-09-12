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
VERSION="0.9.5-ddp-native-atp-r7j-deep-retry"

if [ ! -x "$PULL" ]; then
    echo "ERROR: downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7j-deep-retry.sh" >&2
    exit 1
fi

strings "$PULL" | grep -F "$VERSION" >/dev/null || {
    echo "ERROR: downloader is not an R7J build; refusing stale binary." >&2
    echo "Rebuild with:" >&2
    echo "  sh scripts/build-r7j-deep-retry.sh" >&2
    exit 1
}
strings "$PULL" | grep -F 'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: downloader lacks R7J deep metadata recovery." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: downloader lacks R7I.2 strict identity validation." >&2
    exit 1
}

mkdir -p "$DEST"

echo
echo "R7J deep-recovery persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Binary:      R7J version/recovery markers verified"
echo "Base:        proven R7I.2 / R7E healthy path"
echo "Traversal:   R7C ParentDirID/DID reuse"
echo "Recovery:    R7D DID rebuild + R7I same-file offset resume"
echo "Data budget: up to 6 in-process recoveries per file"
echo "Meta budget: up to 6 reconnect/re-prime cycles per metadata operation"
echo "DID gate:    metadata retry only after successful parent-DID prime"
echo "Settle:      1 second, recovery path only"
echo "Validation:  required nonzero AFP CNID/NodeID + exact data-fork size"
echo "Empty forks: R7E known zero-byte data-fork skip retained"
echo "ATP timer:   2 seconds"
echo "ATP budget:  initial request + up to 5 retransmissions (unchanged)"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
