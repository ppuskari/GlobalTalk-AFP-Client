#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-stable-r7"
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
VERSION="0.9.5-ddp-native-atp-r7s-localtalk-endurance"

# Reconstruct the currently proven Stable R7Q + R7R candidate first.
sh "$ROOT/scripts/build-stable-r7q-ui.sh"

# Layer only the new long-haul LocalTalk reliability semantics afterward.
python3 "$ROOT/tools/apply_localtalk_endurance_r7s.py" "$CLIENT"

grep -F 'GLOBALTALK LOCALTALK ENDURANCE R7S' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep -F 'R7S: recovery incident cleared' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep -F 'R7S: deferred pass=' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep -F 'R7S: resume-checkpoint' \
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

echo "CC  cmdline/cmdline_afp.c (R7S LocalTalk endurance)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/cmdline/cmdline_afp.c" -o "$CMD_OBJ"

LIBS="$ATPR1 -lpthread -ldl"
PULL="$OUT/gt-afp-pull"

echo "LD  $PULL (R7S LocalTalk endurance)"
"$CC" -o "$PULL" \
    "$OBJ/native_atp.o" \
    "$OBJ"/lib_*.o \
    "$OBJ/daemon_stateless_c.o" \
    "$OBJ/daemon_metadata_c.o" \
    "$CMD_OBJ" \
    "$OBJ/legacy_compat.o" \
    "$OBJ/legacy_batch_main.o" \
    $LIBS

strings "$PULL" | grep -F 'R7S: recovery incident cleared' >/dev/null || {
    echo "ERROR: R7S incident-reset marker missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7S: deferred pass=' >/dev/null || {
    echo "ERROR: R7S deferred retry marker missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7S: deferred retry limit exhausted' >/dev/null || {
    echo "ERROR: R7S five-pass terminal guard missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7S: cross-process resume armed' >/dev/null || {
    echo "ERROR: R7S checkpoint-resume marker missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict identity guard missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7Q: skip-data size=' >/dev/null || {
    echo "ERROR: R7Q completed-file reuse missing." >&2
    exit 1
}

grep -F 'GLOBALTALK RECOVERY DID MULTISLASH R7R' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null || {
    echo "ERROR: R7R // recovery fix missing." >&2
    exit 1
}

python3 -m py_compile "$ROOT/tools/apply_localtalk_endurance_r7s.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-r7s-putty.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-putty.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-r7q.py"

# Exercise the complete nested R7S -> PuTTY -> R7Q source transforms.  --help
# exits from argparse before any AFP connection is attempted, but stale UI
# guards or transform syntax errors still fail the build here.
python3 "$ROOT/scripts/gt-pull-stable.py" --help >/dev/null

sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "R7S LocalTalk endurance build ready."
echo "  baseline:           Stable R7Q + R7R"
echo "  ATP profile:        7 sends / 2 sec / 50 ms"
echo "  recovery budget:    6 consecutive no-progress recoveries per incident"
echo "  budget reset:       first verified resumed data clears incident count"
echo "  checkpoint:         512 KiB durable intervals, CNID + exact size gated"
echo "  completed reuse:    durable checkpoint preferred over mtime shortcut"
echo "  first pass:         unrecovered file deferred; tree continues"
echo "  deferred retries:   fresh AFP connection per pass"
echo "  deferred cap:       5 passes, then list unresolved and exit nonzero"
echo "  server-away bound:  finite; no unbounded deferred reconnect loop"
echo "  browser:            $ROOT/scripts/gt-afp-browser.sh"
