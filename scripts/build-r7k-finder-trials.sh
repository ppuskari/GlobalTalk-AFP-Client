#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-r7k-trials"
OBJ="$OUT/obj"
VERSION="0.9.5-ddp-native-atp-r7k-finder-trials"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
NATIVE="/tmp/gt_atp_compat.r7k.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

# First reconstruct and verify the exact full-tree R7J baseline that completed
# the torture set.  R7K is layered only after that build succeeds.
sh "$ROOT/scripts/build-r7j-deep-retry.sh"

python3 "$ROOT/tools/apply_r7k_runtime_trials.py" "$CLIENT"

grep 'GLOBALTALK DEEP RECOVERY R7J' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK FINDER TOLERANCE R7K' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK FINDER TOLERANCE R7K' \
    "$CLIENT/lib/asp_transport.c" >/dev/null
test "$(grep -c 'r7k_atp_total_sends()' \
    "$CLIENT/lib/asp_transport.c")" -eq 2

python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"
grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

test -f "$ATPR1" || {
    echo "ERROR: private ATP-R1 archive missing: $ATPR1" >&2
    exit 1
}

CC=${CC:-cc}
rm -rf "$OUT"
mkdir -p "$OBJ"

CFLAGS="-O2 -g -std=gnu11 -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64"
CFLAGS="$CFLAGS -DAFPCLIENT_INTERNAL"
CFLAGS="$CFLAGS -DNETATALK_CLIENT_VERSION=\"$VERSION\""
CFLAGS="$CFLAGS -DBINDIR=\"$OUT\""
CFLAGS="$CFLAGS -DHAVE_SYS_XATTR_H"

INCLUDES="-I$CLIENT -I$CLIENT/include -I$CLIENT/lib"
INCLUDES="$INCLUDES -I$CLIENT/daemon -I$CLIENT/cmdline"
INCLUDES="$INCLUDES -I$ROOT/legacy -I/usr/local/include"

LIB_SOURCES="
lib/afp.c
lib/asp_transport.c
lib/afp_url.c
lib/client.c
lib/codepage.c
lib/connect.c
lib/daemon_signals.c
lib/daemon_socket.c
lib/debug.c
lib/did.c
lib/dsi.c
lib/explicit_bzero.c
lib/forklist.c
lib/identify.c
lib/log.c
lib/loop.c
lib/lowlevel.c
lib/map_def.c
lib/midlevel.c
lib/proto_attr.c
lib/proto_desktop.c
lib/proto_directory.c
lib/proto_files.c
lib/proto_fork.c
lib/proto_login.c
lib/proto_map.c
lib/proto_replyblock.c
lib/proto_server.c
lib/proto_session.c
lib/proto_volume.c
lib/resource.c
lib/server.c
lib/status.c
lib/uams.c
lib/uams_clrtxt.c
lib/uams_def.c
lib/unicode.c
lib/users.c
lib/utils.c
"

PULL_SOURCES="
daemon/stateless.c
daemon/metadata.c
cmdline/cmdline_afp.c
"

DAEMON_SOURCES="
daemon/daemon.c
daemon/commands.c
daemon/daemon_client.c
"

CORE_OBJECTS=""
PULL_OBJECTS=""
DAEMON_OBJECTS=""

compile_client_source()
{
    src=$1
    stem=$(printf '%s' "$src" | sed 's#[/.]#_#g')
    obj="$OBJ/$stem.o"
    echo "CC  $src"
    "$CC" $CFLAGS $INCLUDES \
        -include "$ROOT/legacy/legacy_compat.h" \
        -c "$CLIENT/$src" -o "$obj"
    LAST_OBJ="$obj"
}

for src in $LIB_SOURCES; do
    compile_client_source "$src"
    CORE_OBJECTS="$CORE_OBJECTS $LAST_OBJ"
done
for src in $PULL_SOURCES; do
    compile_client_source "$src"
    PULL_OBJECTS="$PULL_OBJECTS $LAST_OBJ"
done
for src in $DAEMON_SOURCES; do
    compile_client_source "$src"
    DAEMON_OBJECTS="$DAEMON_OBJECTS $LAST_OBJ"
done

LEGACY_COMPAT_OBJ="$OBJ/legacy_compat.o"
echo "CC  legacy/legacy_compat.c"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_compat.c" -o "$LEGACY_COMPAT_OBJ"

LEGACY_MAIN_OBJ="$OBJ/legacy_batch_main.o"
echo "CC  legacy/legacy_batch_main.c"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_batch_main.c" -o "$LEGACY_MAIN_OBJ"

LEGACY_LS_OBJ="$OBJ/legacy_ls_main.o"
echo "CC  legacy/legacy_ls_main.c"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_ls_main.c" -o "$LEGACY_LS_OBJ"

LEGACY_PUSH_OBJ="$OBJ/legacy_push_main.o"
echo "CC  legacy/legacy_push_main.c"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_push_main.c" -o "$LEGACY_PUSH_OBJ"

LEGACY_META_OBJ="$OBJ/legacy_meta_main.o"
echo "CC  legacy/legacy_meta_main.c"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_meta_main.c" -o "$LEGACY_META_OBJ"

NATIVE_ATP_OBJ="$OBJ/native_atp.o"
echo "CC  $NATIVE"
"$CC" $CFLAGS $INCLUDES -include "$ROOT/legacy/legacy_compat.h" \
    -c "$NATIVE" -o "$NATIVE_ATP_OBJ"

LIBS="$ATPR1 -lpthread -ldl"

echo "LD  $OUT/afpsld"
"$CC" -o "$OUT/afpsld" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $DAEMON_OBJECTS $LEGACY_COMPAT_OBJ $LIBS

echo "LD  $OUT/gt-afp-pull"
"$CC" -o "$OUT/gt-afp-pull" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS \
    $LEGACY_COMPAT_OBJ $LEGACY_MAIN_OBJ $LIBS

echo "LD  $OUT/gt-afp-ls"
"$CC" -o "$OUT/gt-afp-ls" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS \
    $LEGACY_COMPAT_OBJ $LEGACY_LS_OBJ $LIBS

echo "LD  $OUT/gt-afp-push"
"$CC" -o "$OUT/gt-afp-push" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS \
    $LEGACY_COMPAT_OBJ $LEGACY_PUSH_OBJ $LIBS

echo "LD  $OUT/gt-afp-meta"
"$CC" -o "$OUT/gt-afp-meta" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS \
    $LEGACY_COMPAT_OBJ $LEGACY_META_OBJ $LIBS

for binary in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta
do
    strings "$OUT/$binary" | grep 'GLOBALTALK NATIVE ATP R1' >/dev/null || {
        echo "ERROR: native ATP marker missing from $binary" >&2
        exit 1
    }
    strings "$OUT/$binary" | grep -F "$VERSION" >/dev/null || {
        echo "ERROR: R7K version marker missing from $binary" >&2
        exit 1
    }
done

strings "$OUT/gt-afp-pull" | grep -F \
    'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: R7J recovery baseline missing from R7K." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing control missing." >&2
    exit 1
}
strings "$OUT/afpsld" | grep -F \
    'GT_AFP_R7K_ATP_SENDS' >/dev/null || {
    echo "ERROR: R7K ATP-send control missing from afpsld." >&2
    exit 1
}

python3 -m py_compile "$ROOT/tools/apply_r7k_runtime_trials.py"
sh -n "$ROOT/scripts/gt-pull-r7k.sh"

echo
echo "R7K Finder-tolerance trial build ready."
echo "Baseline: R7J full-tree PASS recovery behavior"
echo "R7J data/session recovery budget: retained at 6"
echo "R7I.2 CNID + exact-size resume validation: retained"
echo "ATP timer: fixed at 2 seconds"
echo "Runtime ATP total sends: selectable 6..12, default 6"
echo "Runtime post-object pacing: selectable 0..250 ms, default 0"
echo "Trial control:   6 sends, 0 ms"
echo "Trial patient:  10 sends, 0 ms"
echo "Trial paced:     6 sends, 50 ms"
echo "Trial combined: 10 sends, 50 ms"
echo "Output: $OUT"
echo "Final binaries: R7K markers verified"
echo
echo "Run after ./scripts/gt-afp-reset.sh:"
echo "  sh scripts/gt-pull-r7k.sh control  'AFP_URL' 'DEST'"
echo "  sh scripts/gt-pull-r7k.sh patient  'AFP_URL' 'DEST'"
echo "  sh scripts/gt-pull-r7k.sh paced    'AFP_URL' 'DEST'"
echo "  sh scripts/gt-pull-r7k.sh combined 'AFP_URL' 'DEST'"
