#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r4"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Reconstruct every R3/R4-touched generated source from the pinned 0.9.5
# nested checkout.  This never resets or cleans the parent repository.
for path in \
    lib/lowlevel.c \
    lib/afp_url.c \
    lib/server.c \
    lib/midlevel.c \
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

# Preserve every hardware-proven R3 correction.
python3 "$ROOT/tools/apply_ddp_rooted_url.py" "$CLIENT"
if [ -f "$ROOT/tools/apply_ddp_credentials.py" ]; then
    python3 "$ROOT/tools/apply_ddp_credentials.py" "$CLIENT"
fi
python3 "$ROOT/tools/apply_rfork_r3_forkstate.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_batch.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp_at_version_cap.py" "$CLIENT"

# R4 changes only resource-fork transfer lifetime: one remote FPOpenFork for
# the entire local copy, large stateful reads, then one FPCloseFork.
python3 "$ROOT/tools/apply_rfork_r4_stream.py" "$CLIENT"

# Reuse the proven R2 transport/WRTCONT/ATP-R1 builder underneath R4.
RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r4" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R4
R3 correctness baseline plus stateful resource-fork streaming:
- all R3 rooted-path, fork-state, ASP and auto-version corrections retained
- resource fork opened once for the complete remote-to-local copy
- stateful afpsld file handle reused across the complete resource fork
- client read block 101728 bytes = 22 * 4624-byte ASP response ceiling
- ASP wire transaction ceiling remains 4624 bytes
- R3 16 KiB metadata limit remains unchanged for ordinary metadata/xattrs
EOF

# Production candidate must not contain the old diagnostic overlays.
for binary in gt-afp-pull gt-afp-ls afpsld
do
    if strings "$OUT/$binary" | \
        grep -E 'R2B META|R2C READ|R2D READ|R2E OPEN' >/dev/null 2>&1; then
        echo "ERROR: diagnostic marker leaked into R4 $binary." >&2
        exit 1
    fi
done

strings "$OUT/gt-afp-pull" | grep '0.9.5-ddp-rfork-r4' >/dev/null
strings "$OUT/gt-afp-ls" | grep '0.9.5-ddp-rfork-r4' >/dev/null

# Confirm the stateful resource-open path is actually linked into both sides.
nm "$OUT/afpsld" | grep ' ml_open_resourcefork$' >/dev/null
nm "$OUT/gt-afp-pull" | grep ' afp_sl_open_resourcefork$' >/dev/null

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
echo "ASP resource-fork R4 streaming tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-ls"
echo
echo "Version marker: 0.9.5-ddp-rfork-r4"
echo "Resource stream: one open / stateful reads / one close"
echo "Resource stream block: 101728 bytes (22 * 4624)"
echo "ASP response ceiling: 4624 bytes"
echo "Ordinary metadata batch: 16384 bytes"
echo "ASP/DDP auto AFP ceiling: 2.2"
echo "R4 contains no R2B/R2C/R2D/R2E diagnostic overlays."
