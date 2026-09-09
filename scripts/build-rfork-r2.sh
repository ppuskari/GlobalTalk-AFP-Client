#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT=${RFORK_OUT:-"$ROOT/build-rfork-r2"}
VERSION=${RFORK_VERSION:-"0.9.5-ddp-rfork-r2"}
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"

if [ ! -f "$CLIENT/lib/asp_transport.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Refresh the tracked transport overlay first, then layer the R2 hardware-test
# patch onto the generated work tree. The tracked Phase-1 overlay is not
# modified, so the normal build remains an easy rollback path.
mkdir -p "$CLIENT/include/atalk"
cp "$ROOT/overlay/include/atalk/asp.h" \
   "$CLIENT/include/atalk/asp.h"
cp "$ROOT/overlay/include/asp_transport.h" \
   "$CLIENT/include/asp_transport.h"
cp "$ROOT/overlay/lib/asp_transport.c" \
   "$CLIENT/lib/asp_transport.c"

python3 "$ROOT/tools/apply_daemon_asp_compat.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp_version_selector.py" "$CLIENT"

# Debian 8 Jessie ships Python 3.4. Its pathlib.Path lacks read_text() and
# write_text(). Execute the guarded R2 patcher through the same compatibility
# shims used by bootstrap-linux.sh so the test branch remains Jessie-native.
python3 - "$ROOT/tools/apply_rfork_r2.py" "$CLIENT" <<'PY'
import io
import pathlib
import runpy
import sys

if not hasattr(pathlib.Path, "read_text"):
    def read_text(self, encoding="utf-8", errors=None):
        with io.open(str(self), "r", encoding=encoding, errors=errors) as f:
            return f.read()
    pathlib.Path.read_text = read_text

if not hasattr(pathlib.Path, "write_text"):
    def write_text(self, data, encoding="utf-8", errors=None):
        with io.open(str(self), "w", encoding=encoding, errors=errors) as f:
            return f.write(data)
    pathlib.Path.write_text = write_text

script = sys.argv[1]
target = sys.argv[2]
sys.argv = [script, target]
runpy.run_path(script, run_name="__main__")
PY

# Native ATP builds make ASP command waiting bidirectional, restore classic ASP
# workstation tickles for fd-less DDP sessions, and keep that tickle cadence
# alive even while sustained AFP traffic prevents the generic loop from idling.
if [ -n "${RFORK_NATIVE_ATP_SOURCE:-}" ]; then
    python3 "$ROOT/tools/apply_native_asp_control.py" "$CLIENT"
    python3 "$ROOT/tools/apply_asp_session_tickle_r2.py" "$CLIENT"
    python3 "$ROOT/tools/apply_busy_session_tickle_r2.py" "$CLIENT"
    python3 "$ROOT/tools/apply_batch_integrity_r2.py" "$CLIENT"

    grep 'GLOBALTALK NATIVE ASP CONTROL R1' \
        "$CLIENT/lib/asp_transport.c" >/dev/null
    grep 'GLOBALTALK ASP SESSION TICKLE R2' \
        "$CLIENT/lib/asp_transport.c" >/dev/null
    grep 'GLOBALTALK BUSY SESSION TICKLE R2B' \
        "$CLIENT/lib/asp_transport.c" >/dev/null
    grep 'GLOBALTALK BATCH INTEGRITY R2' \
        "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
fi

# Keep the private historical libatalk archive available for NBP and the
# remaining AppleTalk helpers. A native ATP object, when requested below,
# defines the public ATP entry points first so the archive ATP objects are not
# pulled by the static linker.
if [ ! -f "$ATPR1" ]; then
    if [ ! -f "$ROOT/libatalk-atp-r1/build-atalk-r1.sh" ]; then
        echo "ERROR: ATP-R1 helper package missing." >&2
        exit 1
    fi
    sh "$ROOT/libatalk-atp-r1/build-atalk-r1.sh"
fi

test -f "$ATPR1" || {
    echo "ERROR: private ATP-R1 archive was not built: $ATPR1" >&2
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
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_compat.c" -o "$LEGACY_COMPAT_OBJ"

LEGACY_MAIN_OBJ="$OBJ/legacy_batch_main.o"
echo "CC  legacy/legacy_batch_main.c"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_batch_main.c" -o "$LEGACY_MAIN_OBJ"

LEGACY_LS_OBJ="$OBJ/legacy_ls_main.o"
echo "CC  legacy/legacy_ls_main.c"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_ls_main.c" -o "$LEGACY_LS_OBJ"

LEGACY_PUSH_OBJ="$OBJ/legacy_push_main.o"
echo "CC  legacy/legacy_push_main.c"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_push_main.c" -o "$LEGACY_PUSH_OBJ"

LEGACY_META_OBJ="$OBJ/legacy_meta_main.o"
echo "CC  legacy/legacy_meta_main.c"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$ROOT/legacy/legacy_meta_main.c" -o "$LEGACY_META_OBJ"

NATIVE_ATP_OBJ=""
if [ -n "${RFORK_NATIVE_ATP_SOURCE:-}" ]; then
    test -f "$RFORK_NATIVE_ATP_SOURCE" || {
        echo "ERROR: native ATP source not found: $RFORK_NATIVE_ATP_SOURCE" >&2
        exit 1
    }
    NATIVE_ATP_OBJ="$OBJ/native_atp.o"
    echo "CC  $RFORK_NATIVE_ATP_SOURCE"
    "$CC" $CFLAGS $INCLUDES \
        -include "$ROOT/legacy/legacy_compat.h" \
        -c "$RFORK_NATIVE_ATP_SOURCE" -o "$NATIVE_ATP_OBJ"
fi

LIBS="$ATPR1 -lpthread -ldl"

echo "LD  $OUT/afpsld"
"$CC" -o "$OUT/afpsld" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $DAEMON_OBJECTS $LEGACY_COMPAT_OBJ \
    $LIBS

echo "LD  $OUT/gt-afp-pull"
"$CC" -o "$OUT/gt-afp-pull" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS $LEGACY_COMPAT_OBJ $LEGACY_MAIN_OBJ \
    $LIBS

echo "LD  $OUT/gt-afp-ls"
"$CC" -o "$OUT/gt-afp-ls" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS $LEGACY_COMPAT_OBJ $LEGACY_LS_OBJ \
    $LIBS

echo "LD  $OUT/gt-afp-push"
"$CC" -o "$OUT/gt-afp-push" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS $LEGACY_COMPAT_OBJ $LEGACY_PUSH_OBJ \
    $LIBS

echo "LD  $OUT/gt-afp-meta"
"$CC" -o "$OUT/gt-afp-meta" \
    $NATIVE_ATP_OBJ $CORE_OBJECTS $PULL_OBJECTS $LEGACY_COMPAT_OBJ $LEGACY_META_OBJ \
    $LIBS

echo
echo "ASP resource-fork tools built:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-ls"
echo "  $OUT/gt-afp-push"
echo "  $OUT/gt-afp-meta"
echo
echo "Version marker: $VERSION"
echo "Private libatalk: $ATPR1"
if [ -n "$NATIVE_ATP_OBJ" ]; then
    echo "ATP transaction engine: native override ($RFORK_NATIVE_ATP_SOURCE)"
    echo "ASP interleaved controls: enabled"
    echo "ASP client tickle endpoint/wire fix: enabled"
    echo "ASP busy-transfer tickle scheduler: enabled"
    echo "Batch archive integrity checks: enabled"
else
    echo "ATP transaction engine: private libatalk ATP-R1"
fi
echo
echo "Use the tool help for URL syntax and examples:"
echo "  $OUT/gt-afp-pull -h"
echo "  $OUT/gt-afp-push -h"
echo "  $OUT/gt-afp-ls -h"
echo "  $OUT/gt-afp-meta -h"
