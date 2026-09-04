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

# Netatalk's public <atalk/asp.h> includes its own AFP declarations, which
# collide with Netatalk Client 0.9.5's afp_protocol.h.  The DDP transport
# only needs ASP wire constants, so install our local wire-only shim ahead
# of /usr/local/include in the include search path.
mkdir -p "$CLIENT/include/atalk"
cp "$ROOT/overlay/include/atalk/asp.h" \
   "$CLIENT/include/atalk/asp.h"

CC=${CC:-cc}

rm -rf "$OUT"
mkdir -p "$OBJ"

CFLAGS="-O2 -g -std=gnu11 -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64"
CFLAGS="$CFLAGS -DAFPCLIENT_INTERNAL"
CFLAGS="$CFLAGS -DNETATALK_CLIENT_VERSION=\"0.9.5-ddp-legacy\""
CFLAGS="$CFLAGS -DBINDIR=\"/usr/local/bin\""
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

EXTRA_SOURCES="
daemon/stateless.c
daemon/metadata.c
cmdline/cmdline_afp.c
"

OBJECTS=""

compile_client_source()
{
    src=$1
    base=$(basename "$src" .c)
    obj="$OBJ/$base.o"
    echo "CC  $src"
    "$CC" $CFLAGS $INCLUDES \
        -include "$ROOT/legacy/legacy_compat.h" \
        -c "$CLIENT/$src" -o "$obj"
    OBJECTS="$OBJECTS $obj"
}

for src in $LIB_SOURCES $EXTRA_SOURCES; do
    compile_client_source "$src"
done

for src in legacy_compat.c legacy_batch_main.c; do
    base=$(basename "$src" .c)
    obj="$OBJ/$base.o"
    echo "CC  legacy/$src"
    "$CC" $CFLAGS $INCLUDES \
        -include "$ROOT/legacy/legacy_compat.h" \
        -c "$ROOT/legacy/$src" -o "$obj"
    OBJECTS="$OBJECTS $obj"
done

echo "LD  $OUT/gt-afp-pull"
"$CC" -o "$OUT/gt-afp-pull" $OBJECTS \
    -L/usr/local/lib -latalk -lpthread -ldl

echo
echo "Legacy batch client built:"
echo "  $OUT/gt-afp-pull"
echo
echo "Usage test:"
echo "  $OUT/gt-afp-pull -h"
echo
echo "GlobalTalk example:"
echo "  $OUT/gt-afp-pull -r -V -M netatalk \\" 
echo "    'afp+ddp://BLIHNMNTE01@HuskyNet Global/VOLUME/path' \\" 
echo "    /srv/netatalk/archive"
