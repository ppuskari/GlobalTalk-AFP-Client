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
RESET="$ROOT/scripts/gt-afp-reset.sh"
USER_NAME=${USER:-$(id -un)}
MAX_ATTEMPTS=${GT_AFP_PULL_ATTEMPTS:-3}

case "$MAX_ATTEMPTS" in
    ''|*[!0-9]*)
        echo "ERROR: GT_AFP_PULL_ATTEMPTS must be a positive integer." >&2
        exit 2
        ;;
esac

if [ "$MAX_ATTEMPTS" -lt 1 ]; then
    echo "ERROR: GT_AFP_PULL_ATTEMPTS must be at least 1." >&2
    exit 2
fi

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

ATTEMPT=1

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
    if [ "$ATTEMPT" -gt 1 ]; then
        echo
        echo "Retrying recursive download from the same remote base."
        echo "Attempt $ATTEMPT of $MAX_ATTEMPTS."
        echo "Existing completed files may be transferred again."
        echo
    fi

    if "$PULL" \
        -r \
        -V \
        -M netatalk \
        "$SOURCE" \
        "$DEST"; then
        echo
        echo "Download complete."
        echo "Files landed directly in:"
        echo "  $DEST"
        exit 0
    fi

    RC=$?

    echo >&2
    echo "Recursive AFP pull failed on attempt $ATTEMPT of $MAX_ATTEMPTS." >&2
    echo "The current afpsld session may no longer be usable." >&2

    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
        echo "Retry limit reached; leaving partial results in place." >&2
        exit "$RC"
    fi

    if [ ! -x "$RESET" ]; then
        echo "Cannot recover: reset helper not found:" >&2
        echo "  $RESET" >&2
        exit "$RC"
    fi

    echo "Restarting afpsld before retry..."
    if ! "$RESET"; then
        echo "AFP daemon reset was refused or failed." >&2
        echo "No retry will be attempted because another AFP client may be active." >&2
        exit "$RC"
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
done

exit 1
