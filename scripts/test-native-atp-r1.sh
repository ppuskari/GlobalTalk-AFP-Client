#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BIN="$ROOT/build-native-atp-r1"

usage()
{
    echo "Usage:" >&2
    echo "  sh scripts/test-native-atp-r1.sh SOURCE_AFP_URL LOCAL_ROOT [WRITE_AFP_URL]" >&2
    echo >&2
    echo "SOURCE_AFP_URL may name a file or directory." >&2
    echo "LOCAL_ROOT should be on a filesystem with enough free space." >&2
    echo "If WRITE_AFP_URL is supplied, the pulled result is pushed there." >&2
    exit 2
}

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage

SOURCE=$1
LOCAL_ROOT=$2
WRITE_URL=${3:-}
STAMP=$(date '+%Y%m%d-%H%M%S')
DEST="$LOCAL_ROOT/native-atp-r1-$STAMP"
LOG="$LOCAL_ROOT/native-atp-r1-$STAMP.log"

for tool in afpsld gt-afp-ls gt-afp-pull gt-afp-push; do
    test -x "$BIN/$tool" || {
        echo "ERROR: missing $BIN/$tool" >&2
        echo "Build first: sh scripts/build-native-atp-r1.sh" >&2
        exit 1
    }
done

mkdir -p "$LOCAL_ROOT" "$DEST"

# Never accidentally reuse an R4/R4C daemon with the native client tools.
pkill -u "$USER" -x afpsld 2>/dev/null || true
sleep 1

{
    echo "Native ATP R1 hardware smoke"
    echo "Started: $(date)"
    echo "Source:  $SOURCE"
    echo "Local:   $DEST"
    if [ -n "$WRITE_URL" ]; then
        echo "Write:   $WRITE_URL"
    fi
    echo

    echo "===== SOURCE LIST ====="
    "$BIN/gt-afp-ls" "$SOURCE"

    echo
    echo "===== GLOBALTALK -> LOCAL PULL ====="
    "$BIN/gt-afp-pull" -r -V -M netatalk \
        "$SOURCE" "$DEST"

    echo
    echo "===== LOCAL RESULT ====="
    find "$DEST" -maxdepth 3 -type f -printf '%s\t%p\n' \
        2>/dev/null | head -200 || true

    if [ -n "$WRITE_URL" ]; then
        echo
        echo "===== LOCAL -> GLOBALTALK PUSH ====="
        "$BIN/gt-afp-push" -r -V -M netatalk \
            "$DEST" "$WRITE_URL"
    fi

    echo
    echo "PASS: native ATP R1 hardware smoke"
    echo "Finished: $(date)"
} 2>&1 | tee "$LOG"

echo
echo "Output retained:"
echo "  $DEST"
echo "Log retained:"
echo "  $LOG"
