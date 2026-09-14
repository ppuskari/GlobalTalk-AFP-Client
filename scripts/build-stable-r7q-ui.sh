#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-stable-r7"
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
VERSION="0.9.5-ddp-native-atp-stable-r7q"

# First reconstruct Stable R7 + R7P authoritative progress telemetry.
sh "$ROOT/scripts/build-stable-r7.sh"

# Add retry-safe handling for already-completed destination files.
python3 "$ROOT/tools/apply_retry_existing_r7q.py" "$CLIENT"

grep 'GLOBALTALK RETRY EXISTING R7Q' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7Q: skip-data size=' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

CC=${CC:-cc}
CFLAGS="-O2 -g -std=gnu11 -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64"
CFLAGS="$CFLAGS -DAFPCLIENT_INTERNAL"
CFLAGS="$CFLAGS -DNETATALK_CLIENT_VERSION=\"$VERSION\""
CFLAGS="$CFLAGS -DBINDIR=\"$OUT\""
CFLAGS="$CFLAGS -DHAVE_SYS_XATTR_H"
INCLUDES="-I$CLIENT -I$CLIENT/include -I$CLIENT/lib"
INCLUDES="$INCLUDES -I$CLIENT/daemon -I$CLIENT/cmdline"
INCLUDES="$INCLUDES -I$ROOT/legacy -I/usr/local/include"

CMD_OBJ="$OBJ/cmdline_cmdline_afp_c.o"

echo "CC  cmdline/cmdline_afp.c (Stable R7 + R7P + R7Q)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/cmdline/cmdline_afp.c" -o "$CMD_OBJ"

LIBS="$ATPR1 -lpthread -ldl"
PULL="$OUT/gt-afp-pull"

echo "LD  $PULL (Stable R7 + R7P + R7Q)"
"$CC" -o "$PULL" \
    "$OBJ/native_atp.o" \
    "$OBJ"/lib_*.o \
    "$OBJ/daemon_stateless_c.o" \
    "$OBJ/daemon_metadata_c.o" \
    "$CMD_OBJ" \
    "$OBJ/legacy_compat.o" \
    "$OBJ/legacy_batch_main.o" \
    $LIBS

strings "$PULL" | grep -F 'R7Q: skip-data size=' >/dev/null || {
    echo "ERROR: R7Q skip marker missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7Q: overwrite-local path=' >/dev/null || {
    echo "ERROR: R7Q overwrite marker missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7P: data path=' >/dev/null || {
    echo "ERROR: R7P data telemetry missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery loop missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict resume identity missing." >&2
    exit 1
}

python3 -m py_compile "$ROOT/tools/apply_retry_existing_r7q.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-r7q.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-putty.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable.py"
python3 -m py_compile "$ROOT/scripts/gt-afp-browser.py"
python3 -m py_compile "$ROOT/scripts/gt-afp-browser-utf8.py"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "Stable R7Q retry-safe UI build ready."
echo "  AFP profile:       7 sends / 2 sec / 50 ms"
echo "  progress:          R7P authoritative AFP payload"
echo "  PuTTY display:      one physical live line, terminal-width capped"
echo "  UTF-8 paths:        explicit UTF-8 argv on Jessie/Python 3.4"
echo "  existing match:    exact size + preserved mtime => skip data"
echo "  skipped metadata:  FinderInfo/resource fork refreshed"
echo "  existing mismatch: overwrite from byte zero"
echo "  partial resume:     never trusted across separate processes"
echo "  browser:            $ROOT/scripts/gt-afp-browser.sh"
