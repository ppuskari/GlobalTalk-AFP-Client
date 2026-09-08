#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-native-atp-r1"
VERSION="0.9.5-ddp-native-atp-r1"
NATIVE="$ROOT/native/gt_atp_compat.c"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

test -f "$NATIVE" || {
    echo "ERROR: native ATP source missing: $NATIVE" >&2
    exit 1
}

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
python3 "$ROOT/tools/apply_afp_at_version_cap.py" "$CLIENT"
python3 "$ROOT/tools/apply_createdir_reply_compat.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r4_stream.py" "$CLIENT"
python3 "$ROOT/tools/apply_gt_tool_presentation.py" "$CLIENT"

grep 'GLOBALTALK DDP CREDENTIALS' "$CLIENT/lib/afp_url.c" >/dev/null
grep 'GLOBALTALK FPCreateDir REPLY COMPAT' \
    "$CLIENT/lib/proto_directory.c" >/dev/null

# build-rfork-r2.sh layers the proven ASP Write/WriteContinue implementation.
# RFORK_NATIVE_ATP_SOURCE then places our ATP API object before the static
# libatalk archive, so all client ATP transactions resolve to the native engine.
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
- proven R2 WriteContinue path retained above native ATP API

AFP/data path:
- R3 rooted URL and credential parsing retained
- ASP automatic AFP version ceiling <= 2.2 retained
- R3 16 KiB metadata batching retained
- R4 stateful resource-fork stream retained
- clean FPCreateDir reply compatibility retained

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
echo "R4 resource stream: retained"
echo "Authenticated DDP URLs: enabled"
echo "Write/WriteContinue: enabled"
echo "Temporary R4C diagnostics: absent"
