#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
BASE="$ROOT/build-r7m-latency"
OUT="$ROOT/build-stable-r7"
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
VERSION="0.9.5-ddp-native-atp-stable-r7"

# Reconstruct the proven R7M/R7L baseline first.
sh "$ROOT/scripts/build-r7m-recovery-latency.sh"

# Add operator-only progress telemetry.  This changes no AFP request/retry,
# recovery, or write behavior; it only reports byte counters already known by
# the successful data/resource read loops when the wrapper enables it.
python3 "$ROOT/tools/apply_progress_telemetry_r7p.py" "$CLIENT"

grep 'GLOBALTALK PROGRESS TELEMETRY R7P' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7P: data path=' "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7P: resource path=' "$CLIENT/daemon/metadata.c" >/dev/null

rm -rf "$OUT"
cp -a "$BASE" "$OUT"

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
META_OBJ="$OBJ/daemon_metadata_c.o"

echo "CC  cmdline/cmdline_afp.c (Stable R7 + R7P telemetry)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/cmdline/cmdline_afp.c" -o "$CMD_OBJ"

echo "CC  daemon/metadata.c (Stable R7 + R7P telemetry)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/daemon/metadata.c" -o "$META_OBJ"

LIBS="$ATPR1 -lpthread -ldl"
PULL="$OUT/gt-afp-pull"
LS="$OUT/gt-afp-ls"
AFPSLD="$OUT/afpsld"

echo "LD  $PULL (Stable R7 + R7P telemetry)"
"$CC" -o "$PULL" \
    "$OBJ/native_atp.o" \
    "$OBJ"/lib_*.o \
    "$OBJ/daemon_stateless_c.o" \
    "$META_OBJ" \
    "$CMD_OBJ" \
    "$OBJ/legacy_compat.o" \
    "$OBJ/legacy_batch_main.o" \
    $LIBS

for FILE in "$PULL" "$LS" "$AFPSLD"; do
    test -x "$FILE" || {
        echo "ERROR: stable component missing: $FILE" >&2
        exit 1
    }
done

strings "$PULL" | grep -F 'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery loop missing from stable puller." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict resume identity guard missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7M: stage=recover-session' >/dev/null || {
    echo "ERROR: R7M timing instrumentation missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7P: data path=' >/dev/null || {
    echo "ERROR: R7P data progress telemetry missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7P: resource path=' >/dev/null || {
    echo "ERROR: R7P resource progress telemetry missing." >&2
    exit 1
}
strings "$AFPSLD" | grep -F 'GT_AFP_R7K_ATP_SENDS' >/dev/null || {
    echo "ERROR: R7K ATP-send runtime control missing from afpsld." >&2
    exit 1
}
strings "$PULL" | grep -F 'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing control missing from puller." >&2
    exit 1
}

python3 -m py_compile "$ROOT/tools/apply_progress_telemetry_r7p.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-total.py"
python3 -m py_compile "$ROOT/scripts/gt-afp-browser.py"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "GlobalTalk AFP Client Stable R7 UI build ready."
echo "Profile:              7 total ATP sends"
echo "ATP retry timer:      2 seconds"
echo "Post-object pacing:   50 ms"
echo "Data recovery:        R7L bounded six-cycle state machine"
echo "Resume identity:      R7I.2 nonzero CNID + exact fork size"
echo "Recovery timing:      R7M retained for diagnostics"
echo "Progress telemetry:   R7P actual AFP data/resource bytes"
echo "Poison-close skip:    disabled"
echo "Default destination:  /mnt/AFPSERVER/128G2/AFPFILES2"
echo "Interactive browser:  scripts/gt-afp-browser.sh"
echo "Direct pull:          scripts/gt-pull-stable.py"
echo "Output:               $OUT"
