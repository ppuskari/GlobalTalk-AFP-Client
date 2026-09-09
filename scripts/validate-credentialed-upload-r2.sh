#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD="$ROOT/build-native-atp-r1"
PUSH="$BUILD/gt-afp-push"
PULL="$BUILD/gt-afp-pull"

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage:" >&2
    echo "  $0 'afp+ddp://user@server@zone/VOLUME/TestFile' [LOCAL_BACKING_FILE]" >&2
    echo >&2
    echo "Use user@server@zone without a password to get an interactive password prompt." >&2
    echo "If LOCAL_BACKING_FILE is supplied, the test removes that file and its" >&2
    echo "Netatalk .AppleDouble sidecar after a successful round trip." >&2
    exit 2
fi

TARGET=$1
BACKING=${2:-}
REMOTE_NAME=${TARGET##*/}
WORK=$(mktemp -d /tmp/gt-cred-upload-r2.XXXXXX)
LOCAL="$WORK/credential-upload-r2.txt"
PULLDIR="$WORK/pullback"

cleanup()
{
    rm -rf "$WORK"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$PUSH" ] || [ ! -x "$PULL" ]; then
    echo "ERROR: native ATP tools are not built in $BUILD" >&2
    echo "Run: sh scripts/build-native-atp-r1.sh" >&2
    exit 1
fi

mkdir -p "$PULLDIR"
printf 'GlobalTalk credentialed upload R2\n' > "$LOCAL"
printf 'timestamp=%s\n' "$(date +%s)" >> "$LOCAL"
printf 'payload=0123456789abcdefghijklmnopqrstuvwxyz\n' >> "$LOCAL"

pkill -u "$USER" -x afpsld 2>/dev/null || true
sleep 1

echo
echo "============================================================"
echo " CREDENTIALED AFP UPLOAD"
echo "============================================================"
echo "Target: $TARGET"
echo

"$PUSH" -V -M none "$LOCAL" "$TARGET"

echo
echo "============================================================"
echo " AFP PULLBACK VERIFY"
echo "============================================================"
echo

"$PULL" -V -M none "$TARGET" "$PULLDIR"

if [ ! -f "$PULLDIR/$REMOTE_NAME" ]; then
    echo "ERROR: pullback file missing: $PULLDIR/$REMOTE_NAME" >&2
    exit 1
fi

if ! cmp -s "$LOCAL" "$PULLDIR/$REMOTE_NAME"; then
    echo "ERROR: upload/pullback contents differ" >&2
    exit 1
fi

echo
echo "PASS: authenticated AFP upload and pullback matched byte-for-byte."

if [ -n "$BACKING" ]; then
    BDIR=$(dirname "$BACKING")
    BNAME=$(basename "$BACKING")
    rm -f "$BACKING"
    rm -f "$BDIR/.AppleDouble/$BNAME"
    echo "Cleaned local Netatalk backing file: $BACKING"
fi
