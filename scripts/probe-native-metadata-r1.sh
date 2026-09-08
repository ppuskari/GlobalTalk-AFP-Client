#!/bin/sh
# Isolate FinderInfo/resource-fork write operations over native ATP R1.
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BIN="$ROOT/build-native-atp-r1"

if [ "$#" -ne 3 ]; then
    echo "Usage: sh scripts/probe-native-metadata-r1.sh LOCAL_FILE AFP_VOLUME_URL REMOTE_PATH" >&2
    exit 2
fi

LOCAL=$1
BASE=$2
REMOTE=$3
LOCAL_DIR=$(dirname -- "$LOCAL")
LOCAL_BASE=$(basename -- "$LOCAL")
AD="$LOCAL_DIR/.AppleDouble/$LOCAL_BASE"
STAMP=$(date '+%Y%m%d-%H%M%S')
WORK="/mnt/AFPSERVER/128G2/gt-native-atp-r1/meta-probe-$STAMP"
FINFO="$WORK/finderinfo.bin"
RFORK="$WORK/resourcefork.bin"

for tool in afpsld gt-afp-meta gt-afp-ls; do
    if [ ! -x "$BIN/$tool" ]; then
        echo "ERROR: missing $BIN/$tool" >&2
        echo "Build first: sh scripts/build-native-atp-r1.sh" >&2
        exit 1
    fi
done

if [ ! -f "$LOCAL" ]; then
    echo "ERROR: local file not found: $LOCAL" >&2
    exit 1
fi
if [ ! -f "$AD" ]; then
    echo "ERROR: Netatalk AppleDouble sidecar not found: $AD" >&2
    exit 1
fi

mkdir -p "$WORK"

python3 - "$AD" "$FINFO" "$RFORK" <<'PY'
from __future__ import print_function
import struct
import sys

src, finfo, rfork = sys.argv[1:4]
with open(src, 'rb') as f:
    data = f.read()

if len(data) < 26:
    raise SystemExit('AppleDouble file is too short')
magic, version = struct.unpack('>II', data[:8])
if magic != 0x00051607 or version != 0x00020000:
    raise SystemExit('Unexpected AppleDouble header')
count = struct.unpack('>H', data[24:26])[0]
entries = {}
pos = 26
for unused in range(count):
    if pos + 12 > len(data):
        raise SystemExit('Truncated AppleDouble entry table')
    eid, off, length = struct.unpack('>III', data[pos:pos + 12])
    if off + length > len(data):
        raise SystemExit('AppleDouble entry extends past EOF')
    entries[eid] = data[off:off + length]
    pos += 12

finder = entries.get(9)
resource = entries.get(2)
if finder is None or len(finder) != 32:
    raise SystemExit('FinderInfo entry 9 is missing or not 32 bytes')
if resource is None:
    raise SystemExit('ResourceFork entry 2 is missing')

with open(finfo, 'wb') as f:
    f.write(finder)
with open(rfork, 'wb') as f:
    f.write(resource)

print('FinderInfo bytes: %d' % len(finder))
print('ResourceFork bytes: %d' % len(resource))
PY

run_one()
{
    label=$1
    type=$2
    action=$3
    file=${4-}

    pkill -u "$USER" -x afpsld 2>/dev/null || true
    sleep 1
    rm -f /tmp/gt-native-atp-r1.log
    export GT_ATP_TRACE=/tmp/gt-native-atp-r1.log

    echo
    echo "===== $label ====="
    if [ -n "$file" ]; then
        "$BIN/gt-afp-meta" "$BASE" "$type" "$action" "$REMOTE" "$file"
    else
        "$BIN/gt-afp-meta" "$BASE" "$type" "$action" "$REMOTE"
    fi
    rc=$?
    echo "$label RC=$rc"
    if [ -f /tmp/gt-native-atp-r1.log ]; then
        echo "--- ATP tail ---"
        tail -20 /tmp/gt-native-atp-r1.log
    fi
    return 0
}

echo "Local file: $LOCAL"
echo "AppleDouble: $AD"
echo "Remote: $BASE $REMOTE"
echo "Probe scratch: $WORK"

run_one "FinderInfo remove" finderinfo remove
run_one "FinderInfo set" finderinfo set "$FINFO"
run_one "ResourceFork remove" resourcefork remove
run_one "ResourceFork set" resourcefork set "$RFORK"

echo
echo "===== REMOTE LISTING ====="
pkill -u "$USER" -x afpsld 2>/dev/null || true
sleep 1
"$BIN/gt-afp-ls" "$BASE$(dirname -- "$REMOTE")" || true

echo
echo "Probe complete. Scratch retained: $WORK"
