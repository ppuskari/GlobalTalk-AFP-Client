#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-legacy"
OBJ="$OUT/obj"

if [ ! -f "$CLIENT/lib/asp_transport.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Refresh generated overlay files so a git pull is enough to pick up transport
# fixes without forcing a destructive re-bootstrap of the patched 0.9.5 tree.
mkdir -p "$CLIENT/include/atalk"
cp "$ROOT/overlay/include/atalk/asp.h" \
   "$CLIENT/include/atalk/asp.h"
cp "$ROOT/overlay/include/asp_transport.h" \
   "$CLIENT/include/asp_transport.h"
cp "$ROOT/overlay/lib/asp_transport.c" \
   "$CLIENT/lib/asp_transport.c"

# Netatalk Client's stateless daemon historically uses server->fd >= 0 as a
# proxy for a live DSI/TCP connection.  ASP/DDP has no DSI TCP fd, so make
# those checks transport-aware before compiling afpsld.
python3 "$ROOT/tools/apply_daemon_asp_compat.py" "$CLIENT"

CC=${CC:-cc}

rm -rf "$OUT"
mkdir -p "$OBJ"

CFLAGS="-O2 -g -std=gnu11 -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64"
CFLAGS="$CFLAGS -DAFPCLIENT_INTERNAL"
CFLAGS="$CFLAGS -DNETATALK_CLIENT_VERSION=\"0.9.5-ddp-legacy\""
# stateless.c auto-spawns BINDIR/afpsld.  Keep the helper beside gt-afp-pull.
CFLAGS="$CFLAGS -DBINDIR=\"$OUT\""
CFLAGS="$CFLAGS -DHAVE_SYS_XATTR_H"

INCLUDES="-I$CLIENT -I$CLIENT/include -I$CLIENT/lib"
INCLUDES="$INCLUDES -I$CLIENT/daemon -I$CLIENT/cmdline"
INCLUDES="$INCLUDES -I$ROOT/legacy -I/usr/local/include"

# Netatalk Client 0.9.5 libafpclient source list, plus the ASP/DDP overlay.
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

LIBS="-L/usr/local/lib -latalk -lpthread -ldl"

echo "LD  $OUT/afpsld"
"$CC" -o "$OUT/afpsld" \
    $CORE_OBJECTS $DAEMON_OBJECTS $LEGACY_COMPAT_OBJ \
    $LIBS

echo "LD  $OUT/gt-afp-pull"
"$CC" -o "$OUT/gt-afp-pull" \
    $CORE_OBJECTS $PULL_OBJECTS $LEGACY_COMPAT_OBJ $LEGACY_MAIN_OBJ \
    $LIBS

echo
echo "Legacy AFP-over-DDP tools built:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Usage test:"
echo "  $OUT/gt-afp-pull -h"
echo
echo "GlobalTalk example:"
echo "  $OUT/gt-afp-pull -r -V -M netatalk \\" 
echo "    'afp+ddp://BLIHNMNTE01@HuskyNet Global/VOLUME/path' \\" 
echo "    /srv/netatalk/archive"
