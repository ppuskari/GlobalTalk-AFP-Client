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
VERSION="0.9.5-ddp-native-atp-r7i-resume-datafork"

if [ ! -x "$PULL" ]; then
    echo "ERROR: downloader not found:" >&2
    echo "  $PULL" >&2
    echo "Build first with:" >&2
    echo "  sh scripts/build-r7i-resume-datafork.sh" >&2
    exit 1
fi

# R7I intentionally shares R7E's output directory. Refuse to launch unless
# the actual executable contains both the R7I version and resume code.
strings "$PULL" | grep -F "$VERSION" >/dev/null || {
    echo "ERROR: downloader is not an R7I build; refusing stale R7E binary." >&2
    echo "Rebuild with:" >&2
    echo "  sh scripts/build-r7i-resume-datafork.sh" >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I: recovery requested' >/dev/null || {
    echo "ERROR: downloader lacks R7I recovery code." >&2
    exit 1
}

mkdir -p "$DEST"

echo
echo "R7I resumable persistent recursive AFP copy"
echo "Remote base: $SOURCE"
echo "Local base:  $DEST"
echo "Binary:      R7I version/resume markers verified"
echo "Base:        virgin R7E healthy path"
echo "Traversal:   R7C ParentDirID/DID reuse"
echo "Recovery:    R7D DID rebuild + R7I same-file offset resume"
echo "Validation:  fresh size + mtime before every resume"
echo "Budget:      up to 3 in-process recoveries per file"
echo "Empty forks: R7E known zero-byte data-fork skip retained"
echo "ATP timer:   2 seconds"
echo "ATP budget:  initial request + up to 5 retransmissions"
echo

exec "$PULL" -r -V -M netatalk "$SOURCE" "$DEST"
