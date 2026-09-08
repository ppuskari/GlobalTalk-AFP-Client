#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r4p"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

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

python3 "$ROOT/tools/apply_ddp_rooted_url.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_forkstate.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_batch.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp_at_version_cap.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r4_stream.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r4_profile.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r4p" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R4P
Profile-only derivative of hardware-proven R4:
- identical R4 resource fork open/read/close behavior
- identical 101728-byte stateful resource read block
- identical 4624-byte ASP response ceiling
- prints precise resource stream timing split into open/read/local-write/close
- profiling branch only; do not promote timing output into production
EOF

for binary in gt-afp-pull gt-afp-ls afpsld
do
    if strings "$OUT/$binary" | \
        grep -E 'R2B META|R2C READ|R2D READ|R2E OPEN' >/dev/null 2>&1; then
        echo "ERROR: diagnostic marker leaked into R4P $binary." >&2
        exit 1
    fi
done

strings "$OUT/gt-afp-pull" | grep '0.9.5-ddp-rfork-r4p' >/dev/null
nm "$OUT/afpsld" | grep ' ml_open_resourcefork$' >/dev/null
nm "$OUT/gt-afp-pull" | grep ' afp_sl_open_resourcefork$' >/dev/null
strings "$OUT/gt-afp-pull" | grep 'R4PROFILE resource=' >/dev/null

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
echo "R4P profiling tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-ls"
echo
echo "Version marker: 0.9.5-ddp-rfork-r4p"
echo "Resource stream behavior: identical to R4"
echo "Profile output: R4PROFILE resource=... total=... read=... write=..."
echo "Production R4 build remains untouched in build-rfork-r4."
