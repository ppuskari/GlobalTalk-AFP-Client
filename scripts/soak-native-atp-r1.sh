#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BIN="$ROOT/build-native-atp-r1"

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: sh scripts/soak-native-atp-r1.sh WRITE_AFP_URL LOCAL_ROOT [ROUNDS]" >&2
    exit 2
fi

WRITE_URL=$1
LOCAL_ROOT=$2
ROUNDS=${3:-25}
STAMP=$(date '+%Y%m%d-%H%M%S')
WORK="$LOCAL_ROOT/native-atp-soak-$STAMP"
LOG="$LOCAL_ROOT/native-atp-soak-$STAMP.log"

case "$ROUNDS" in
    *[!0-9]*|'')
        echo "ROUNDS must be a positive integer." >&2
        exit 2
        ;;
esac

mkdir -p "$WORK"

for tool in afpsld gt-afp-push gt-afp-ls; do
    test -x "$BIN/$tool" || {
        echo "ERROR: missing $BIN/$tool" >&2
        echo "Build first: sh scripts/build-native-atp-r1.sh" >&2
        exit 1
    }
done

pkill -u "$USER" -x afpsld 2>/dev/null || true
sleep 1

PASS=0
FAIL=0
i=1

{
    echo "Native ATP R1 create/write soak"
    echo "Started: $(date)"
    echo "Write URL: $WRITE_URL"
    echo "Rounds: $ROUNDS"

    while [ "$i" -le "$ROUNDS" ]; do
        NAME=$(printf 'native-atp-%03d-%s' "$i" "$STAMP")
        LOCAL="$WORK/$NAME"

        mkdir -p "$LOCAL"
        printf 'GlobalTalk native ATP R1 round %03d\n' "$i" \
            > "$LOCAL/smoke.txt"

        # Add a payload above one ATP packet so the data-fork write path also
        # has to exercise ASP Write/WriteContinue rather than just creation.
        dd if=/dev/zero of="$LOCAL/payload.bin" \
            bs=1 count=8193 2>/dev/null

        echo
        echo "===== ROUND $i : $NAME ====="

        if "$BIN/gt-afp-push" -r -V -M none \
            "$LOCAL" "$WRITE_URL"
        then
            echo "ROUND $i PASS"
            PASS=$((PASS + 1))
        else
            echo "ROUND $i FAIL"
            FAIL=$((FAIL + 1))
        fi

        i=$((i + 1))
    done

    echo
    echo "========================================"
    echo "NATIVE ATP SOAK: PASS=$PASS FAIL=$FAIL"
    echo "========================================"
    echo "Finished: $(date)"
} 2>&1 | tee "$LOG"

echo
echo "Log retained: $LOG"

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
