#!/bin/sh
set -eu

BASE_LIB=${BASE_LIB:-/usr/local/lib/libatalk.a}
CC=${CC:-gcc}
AR=${AR:-ar}
RANLIB=${RANLIB:-ranlib}
OBJCOPY=${OBJCOPY:-objcopy}

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$SELF_DIR/.." && pwd)
PREFIX=${PREFIX:-"$REPO/legacy/atalk-r1"}

SRC="$SELF_DIR/src/atp_rsel_r1.c"
WORK="$PREFIX/.work"
OUT="$PREFIX/libatalk-atp-r1.a"

echo "== libatalk ATP-R1 private archive builder =="
echo "Repository:   $REPO"
echo "Base library: $BASE_LIB"
echo "Output:       $OUT"

test -f "$BASE_LIB" || {
    echo "ERROR: base libatalk archive not found: $BASE_LIB" >&2
    exit 1
}

test -f /usr/local/include/atalk/atp.h || {
    echo "ERROR: /usr/local/include/atalk/atp.h not found" >&2
    exit 1
}

for t in "$CC" "$AR" "$RANLIB" "$OBJCOPY" nm sha256sum; do
    command -v "$t" >/dev/null 2>&1 || {
        echo "ERROR: required tool not found: $t" >&2
        exit 1
    }
done

rm -rf "$WORK"
mkdir -p "$WORK" "$PREFIX"

cp "$BASE_LIB" "$WORK/libatalk-base.a"

echo
echo "Checking base archive..."
"$AR" t "$WORK/libatalk-base.a" | grep -qx 'atp_rsel.o' || {
    echo "ERROR: base archive does not contain atp_rsel.o" >&2
    exit 1
}

BASE_COUNT=$("$AR" t "$WORK/libatalk-base.a" | wc -l | tr -d ' ')
echo "Base archive members: $BASE_COUNT"

cd "$WORK"
"$AR" x libatalk-base.a atp_rsel.o

test -s atp_rsel.o || {
    echo "ERROR: could not extract atp_rsel.o" >&2
    exit 1
}

echo
echo "Renaming original atp_rsel -> atp_rsel_legacy..."
"$OBJCOPY" \
    --redefine-sym atp_rsel=atp_rsel_legacy \
    atp_rsel.o \
    atp_rsel_legacy.o

echo "Compiling ATP-R1 guard..."
"$CC" \
    -O2 \
    -Wall \
    -Wextra \
    -I/usr/local/include \
    -c "$SRC" \
    -o atp_rsel.o

echo "Building private archive..."
cp libatalk-base.a "$OUT"
"$AR" d "$OUT" atp_rsel.o
"$AR" r "$OUT" atp_rsel_legacy.o atp_rsel.o
"$RANLIB" "$OUT"

echo
echo "Verifying symbols..."
PUB=$(nm -A "$OUT" |
    awk '$NF == "atp_rsel" && $(NF-1) ~ /^[Tt]$/ { n++ } END { print n+0 }')
LEG=$(nm -A "$OUT" |
    awk '$NF == "atp_rsel_legacy" && $(NF-1) ~ /^[Tt]$/ { n++ } END { print n+0 }')

if [ "$PUB" -ne 1 ]; then
    echo "ERROR: expected exactly one public atp_rsel, found $PUB" >&2
    exit 1
fi

if [ "$LEG" -ne 1 ]; then
    echo "ERROR: expected exactly one atp_rsel_legacy, found $LEG" >&2
    exit 1
fi

OUT_COUNT=$("$AR" t "$OUT" | wc -l | tr -d ' ')
EXPECTED=$((BASE_COUNT + 1))

if [ "$OUT_COUNT" -ne "$EXPECTED" ]; then
    echo "ERROR: expected $EXPECTED archive members, found $OUT_COUNT" >&2
    exit 1
fi

echo
echo "PASS: private ATP-R1 archive built"
echo "  $OUT"
echo
echo "SHA256:"
sha256sum "$OUT"

echo
echo "System library was NOT modified:"
echo "  $BASE_LIB"
