#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r1"
NATIVE_SRC="$ROOT/native/gt_atp_compat.c"
# Keep a .c suffix: GCC otherwise treats an extensionless temporary path as
# linker input even when -c is present, so no native_atp.o is produced.
NATIVE="/tmp/gt_atp_compat.jessie.$$.c"

cleanup_native()
{
    rm -f "$NATIVE"
}
trap cleanup_native EXIT HUP INT TERM

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

test -f "$NATIVE_SRC" || {
    echo "ERROR: native ATP source missing: $NATIVE_SRC" >&2
    exit 1
}

# The A2SERVER/Jessie host has historical libatalk development headers. Build
# from a temporary compatibility copy so the tracked native engine remains
# portable across old and current libatalk header layouts.
python3 "$ROOT/tools/prepare_native_atp_jessie.py" \
    "$NATIVE_SRC" "$NATIVE"

grep 'GT_ATP_RESP_MAX 8' "$NATIVE" >/dev/null

# Reconstruct every R3/R4/R4C-touched generated source from pinned 0.9.5.
for path in \
    lib/lowlevel.c \
    lib/afp_url.c \
    lib/server.c \
    lib/midlevel.c \
    lib/proto_directory.c \
    include/midlevel.h \
    daemon/metadata.c \
    daemon/commands.c \
    daemon/stateless.c \
    daemon/daemon_client.h \
    cmdline/cmdline_afp.c \
    cmdline/cmdline_afp.h \
    include/afpsl.h \
    include/afp_server.h
do
    git -C "$CLIENT" show "HEAD:$path" > "$CLIENT/$path"
done

# Preserve the hardware-proven AFP/R3/R4 work above ATP.
python3 "$ROOT/tools/apply_ddp_rooted_url.py" "$CLIENT"
python3 "$ROOT/tools/apply_ddp_credentials.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_forkstate.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_batch.py" "$CLIENT"
python3 "$ROOT/tools/apply_r3_metadata_ipc_frame.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp_at_version_cap.py" "$CLIENT"
python3 "$ROOT/tools/apply_createdir_reply_compat.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r4_stream.py" "$CLIENT"
python3 "$ROOT/tools/apply_gt_tool_presentation.py" "$CLIENT"
python3 "$ROOT/tools/apply_metadata_none_sidecar_filter.py" "$CLIENT"
python3 "$ROOT/tools/apply_classic_posix_metadata_compat.py" "$CLIENT"
python3 "$ROOT/tools/apply_classic_xattr_gate.py" "$CLIENT"

grep 'GLOBALTALK DDP CREDENTIALS' "$CLIENT/lib/afp_url.c" >/dev/null
grep 'GLOBALTALK FPCreateDir REPLY COMPAT' \
    "$CLIENT/lib/proto_directory.c" >/dev/null
grep 'GLOBALTALK R3 32K STATELESS METADATA IPC FRAME' \
    "$CLIENT/daemon/daemon_client.h" >/dev/null
grep 'GLOBALTALK METADATA NONE SIDECAR FILTER R1' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK CLASSIC POSIX METADATA COMPAT R1' \
    "$CLIENT/daemon/commands.c" >/dev/null
grep 'GLOBALTALK CLASSIC AFP XATTR GATE R1' \
    "$CLIENT/daemon/commands.c" >/dev/null

# build-rfork-r2.sh layers the proven ASP Write/WriteContinue implementation.
# RFORK_NATIVE_ATP_SOURCE then places our ATP API object before the static
# libatalk archive, so all client ATP transactions resolve to the native engine.
# The same build also applies the native ASP control patch so synchronous server
# Attention requests are acknowledged while an AFP command is still in flight.
RFORK_OUT="$OUT" \
RFORK_VERSION="$VERSION" \
RFORK_NATIVE_ATP_SOURCE="$NATIVE" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client native ATP R1

Transport:
- Linux AF_APPLETALK/DDP retained
- NBP discovery retained
- libatalk ATP transaction state replaced by native client ATP R1
- explicit outgoing TID/bitmap/retry state
- explicit interleaved incoming TREQ queue
- XO response retransmit cache
- EOM, STS and TREL handling
- ASP OpenSession/command layer retained
- asynchronous ASP Tickle consumption retained
- synchronous ASP Attention requests acknowledged while commands are pending
- proven R2 WriteContinue path retained above native ATP API
- Jessie libatalk header compatibility generated at build time

AFP/data path:
- R3 rooted URL and credential parsing retained
- ASP automatic AFP version ceiling <= 2.2 retained
- R3 16 KiB metadata batching retained
- 32 KiB stateless daemon command frame carries 16 KiB metadata writes safely
- R4 stateful resource-fork stream retained
- clean FPCreateDir reply compatibility retained
- data-only recursive uploads suppress AppleDouble/._ implementation sidecars
- classic servers may omit POSIX chmod/utime support without failing Mac metadata
- AFP 2.x sessions reject AFP3 generic xattrs locally without disturbing FinderInfo/resource forks

Tools:
- gt-afp-ls
- gt-afp-pull
- gt-afp-push
- gt-afp-meta
- afpsld

Optional ATP trace:
  export GT_ATP_TRACE=/mnt/AFPSERVER/128G2/gt-native-atp.log
  (or GT_ATP_TRACE=1 for /tmp/gt-native-atp-r1.log)
EOF

for binary in afpsld gt-afp-ls gt-afp-pull gt-afp-push gt-afp-meta
do
    strings "$OUT/$binary" | grep 'GLOBALTALK NATIVE ATP R1' >/dev/null || {
        echo "ERROR: native ATP marker missing from $binary" >&2
        exit 1
    }
done

strings "$OUT/afpsld" | grep 'ASP attention acknowledged' >/dev/null || {
    echo "ERROR: native ASP Attention handler missing from afpsld" >&2
    exit 1
}

nm "$OUT/afpsld" | grep ' T atp_sreq$' >/dev/null
nm "$OUT/afpsld" | grep ' T atp_rresp$' >/dev/null
nm "$OUT/afpsld" | grep ' T atp_rsel$' >/dev/null
nm "$OUT/afpsld" | grep ' T atp_rreq$' >/dev/null
nm "$OUT/afpsld" | grep ' T atp_sresp$' >/dev/null

if strings "$OUT/afpsld" | grep 'R4C_ASP_XACT' >/dev/null 2>&1; then
    echo "ERROR: temporary R4C ASP diagnostic leaked into native build." >&2
    exit 1
fi
if strings "$OUT/afpsld" | grep 'R4C_MKDIR_DIAG' >/dev/null 2>&1; then
    echo "ERROR: temporary FPCreateDir diagnostic leaked into native build." >&2
    exit 1
fi

if [ -f "$ROOT/tests/test_rfork_r2_model.py" ]; then
    python3 "$ROOT/tests/test_rfork_r2_model.py"
fi
if [ -f "$ROOT/tests/test_rfork_r3_model.py" ]; then
    python3 "$ROOT/tests/test_rfork_r3_model.py"
fi
if [ -f "$ROOT/tests/test_rfork_r4_model.py" ]; then
    python3 "$ROOT/tests/test_rfork_r4_model.py"
fi

echo
echo "Native ATP R1 tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-ls"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-push"
echo "  $OUT/gt-afp-meta"
echo
echo "Version marker: $VERSION"
echo "ATP engine: native R1"
echo "ASP Attention interleave handling: enabled"
echo "Jessie libatalk header compatibility: enabled"
echo "R3 metadata IPC frame: 32768 bytes"
echo "Metadata-none sidecar suppression: enabled"
echo "Classic POSIX metadata compatibility: enabled"
echo "Classic AFP xattr capability gate: enabled"
echo "R4 resource stream: retained"
echo "Authenticated DDP URLs: enabled"
echo "Write/WriteContinue: enabled"
echo "Temporary R4C diagnostics: absent"
