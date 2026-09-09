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
USER_NAME=${USER:-$(id -un)}

if [ ! -x "$PULL" ]; then
    echo "ERROR: downloader not found:" >&2
    echo "  $PULL" >&2
    echo >&2
    echo "Build first:" >&2
    echo "  sh scripts/build-native-atp-r1.sh" >&2
    exit 1
fi

mkdir -p "$DEST"

echo
echo "Remote:"
echo "  $SOURCE"
echo
echo "Direct destination:"
echo "  $DEST"
echo

if pgrep -u "$USER_NAME" -x afpsld >/dev/null 2>&1; then
    echo "AFP daemon:"
    echo "  Reusing existing afpsld."
    echo
    if [ -n "${GT_ATP_TRACE:-}" ]; then
        echo "Trace note:"
        echo "  afpsld is already running."
        echo "  GT_ATP_TRACE from this shell cannot retarget it."
        echo "  The daemon keeps the trace destination inherited"
        echo "  when it was originally started."
        echo
    fi
else
    echo "AFP daemon:"
    echo "  No afpsld is currently running."
    echo "  This client will start the shared daemon."
    if [ -n "${GT_ATP_TRACE:-}" ]; then
        echo
        echo "ATP trace inherited by new daemon:"
        echo "  $GT_ATP_TRACE"
    fi
    echo
fi

OTHER_PULLS=$(pgrep -u "$USER_NAME" -x gt-afp-pull 2>/dev/null || true)

if [ -n "$OTHER_PULLS" ]; then
    echo "Concurrent AFP pull detected."
    echo "Existing gt-afp-pull PID(s):"
    echo "  $OTHER_PULLS"
    echo
    echo "This pull will share the existing afpsld."
    echo "It will NOT terminate the other transfer."
    echo
fi

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
