#!/bin/bash

# Jessie /bin/sh is dash.  Re-exec under Bash so callers can use the same
# "sh scripts/..." convention as the existing benchmark wrappers.
if [ -z "${BASH_VERSION:-}" ]; then
    exec /bin/bash "$0" "$@"
fi

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${GT_AFP_BUILD:-"$ROOT/build-rfork-r4c"}
WORKBASE=${GT_AFP_TEST_ROOT:-"/mnt/AFPSERVER/128G2/gt-afp-r4c-test"}

usage()
{
    cat >&2 <<'EOF'
Usage: sh scripts/run-promotion-roundtrip.sh WRITABLE_AFP_DIRECTORY_URL

The URL must name an existing writable AFP directory, for example:
  afp+ddp://Server@Zone/Volume/Validation

The script creates a uniquely named child directory on that AFP share,
uploads controlled boundary files, writes resource forks and FinderInfo,
pulls the tree back, and verifies every byte locally.
EOF
    exit 2
}

[ "$#" -eq 1 ] || usage
BASE_URL=${1%/}

for tool in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta; do
    if [ ! -x "$BUILD/$tool" ]; then
        echo "Missing R4C tool: $BUILD/$tool" >&2
        echo "Run first: sh scripts/build-rfork-r4c.sh" >&2
        exit 1
    fi
done

STAMP=$(date '+%Y%m%d-%H%M%S')
CORPUS="$WORKBASE/gt-afp-r4c-$STAMP"
PULL_DEST="$WORKBASE/pull-$STAMP"
REMOTE_NAME=$(basename "$CORPUS")
REMOTE_URL="$BASE_URL/$REMOTE_NAME"
LOG="$WORKBASE/roundtrip-$STAMP.log"

mkdir -p "$WORKBASE" "$PULL_DEST"

exec > >(tee "$LOG") 2>&1

echo "R4C controlled promotion round trip"
echo "Build:        $BUILD"
echo "Local corpus: $CORPUS"
echo "Remote base:  $BASE_URL"
echo "Remote test:  $REMOTE_URL"
echo "Pull dest:    $PULL_DEST"
echo "Log:          $LOG"
echo

python3 "$ROOT/tools/make_promotion_corpus.py" "$CORPUS"

pkill -TERM -u "$USER" -x afpsld 2>/dev/null || true
sleep 2

echo
echo "===== WRITE GATE: recursive data upload ====="
"$BUILD/gt-afp-push" -r -V -M netatalk \
    "$CORPUS" \
    "$BASE_URL"

echo
echo "===== WRITE GATE: controlled resource forks ====="
for size in 1 577 578 579 4623 4624 4625 16383 16384 16385; do
    tag=$(printf '%05d' "$size")
    echo "resource fork: $size bytes"
    "$BUILD/gt-afp-meta" \
        "$REMOTE_URL" \
        resourcefork set \
        "resource-targets/rfork-$tag" \
        "$CORPUS/resource-payloads/resource-$tag.bin"
done

echo
echo "===== WRITE GATE: exact FinderInfo ====="
"$BUILD/gt-afp-meta" \
    "$REMOTE_URL" \
    finderinfo set \
    "finder-target" \
    "$CORPUS/finderinfo.bin"

# Read FinderInfo directly before the recursive pull.  This distinguishes a
# metadata write problem from a later tree-copy/AppleDouble problem.
DIRECT_FINDER="$WORKBASE/finder-direct-$STAMP.bin"
"$BUILD/gt-afp-meta" \
    "$REMOTE_URL" \
    finderinfo get \
    "finder-target" \
    "$DIRECT_FINDER"
cmp "$CORPUS/finderinfo.bin" "$DIRECT_FINDER"
echo "PASS: direct FinderInfo readback is byte-exact"

echo
echo "===== READ GATE: recursive pullback ====="
pkill -TERM -u "$USER" -x afpsld 2>/dev/null || true
sleep 2

"$BUILD/gt-afp-pull" -r -V -M netatalk \
    "$REMOTE_URL" \
    "$PULL_DEST"

echo
echo "===== BYTE-EXACT VERIFICATION ====="
python3 "$ROOT/tools/verify_promotion_roundtrip.py" \
    "$CORPUS" \
    "$PULL_DEST"

echo
echo "============================================================"
echo "PASS: R4C controlled promotion hardware gate"
echo "============================================================"
echo "Remote test tree retained for inspection:"
echo "  $REMOTE_URL"
echo "Local artifacts retained:"
echo "  $WORKBASE"
echo "Log:"
echo "  $LOG"
