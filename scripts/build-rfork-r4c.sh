#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r4c"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Reconstruct every R3/R4-touched generated source from pinned 0.9.5.
# This never resets or cleans the parent repository.
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
python3 "$ROOT/tools/apply_ddp_credentials.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_forkstate.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r3_batch.py" "$CLIENT"
python3 "$ROOT/tools/apply_afp_at_version_cap.py" "$CLIENT"

# Guard the authenticated DDP authority parser.  The R4C build reconstructs
# lib/afp_url.c from pinned 0.9.5 on every invocation, so this check prevents
# accidentally shipping a guest-only parser in a later promotion rebuild.
grep 'GLOBALTALK DDP CREDENTIALS' "$CLIENT/lib/afp_url.c" >/dev/null

# Preserve the hardware-proven R4 stateful resource-fork stream unchanged.
python3 "$ROOT/tools/apply_rfork_r4_stream.py" "$CLIENT"

# Presentation-only cleanup: do not advertise the interactive afpcmd ls/cd
# commands from the one-shot gt-afp-ls wrapper.
python3 "$ROOT/tools/apply_gt_tool_presentation.py" "$CLIENT"

# Reuse the proven R2 transport/WRTCONT/ATP-R1 builder.  This promotion build
# also emits gt-afp-push and gt-afp-meta for the remaining hardware gates.
RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r4c" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client R4 promotion candidate

Protocol/data path:
- identical R4 stateful resource-fork streaming architecture
- R3 rooted-path, fork-state, ASP and auto-version corrections retained
- authenticated afp+ddp://user:password@object@zone URLs supported
- resource fork opened once, read statefully, closed once
- resource stream block 101728 bytes = 22 * 4624-byte ASP response ceiling
- ordinary metadata batch remains 16384 bytes

Tooling/presentation:
- gt-afp-ls no longer advertises nonexistent interactive ls/cd commands
- gt-afp-push exposes the existing batch PUT path for hardware write testing
- gt-afp-meta exposes FinderInfo/resource-fork get/set/remove validation
EOF

# Production candidate must not contain old diagnostic overlays.
for binary in gt-afp-pull gt-afp-ls gt-afp-push gt-afp-meta afpsld
do
    if strings "$OUT/$binary" | \
        grep -E 'R2B META|R2C READ|R2D READ|R2E OPEN' >/dev/null 2>&1; then
        echo "ERROR: diagnostic marker leaked into R4C $binary." >&2
        exit 1
    fi
done

# The misleading inherited interactive hint must be absent from the browser.
if strings "$OUT/gt-afp-ls" | \
    grep "Use 'ls' to list available volumes" >/dev/null 2>&1; then
    echo "ERROR: interactive afpcmd hint leaked into gt-afp-ls." >&2
    exit 1
fi

for binary in gt-afp-pull gt-afp-ls gt-afp-push gt-afp-meta; do
    strings "$OUT/$binary" | grep '0.9.5-ddp-rfork-r4c' >/dev/null
done

# Confirm the stateful resource-open path is linked into both sides.
nm "$OUT/afpsld" | grep ' ml_open_resourcefork$' >/dev/null
nm "$OUT/gt-afp-pull" | grep ' afp_sl_open_resourcefork$' >/dev/null
nm "$OUT/gt-afp-push" | grep ' afp_sl_write$' >/dev/null
nm "$OUT/gt-afp-meta" | grep ' com_resourcefork$' >/dev/null
nm "$OUT/gt-afp-meta" | grep ' com_finderinfo$' >/dev/null

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
echo "R4 promotion-candidate tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-ls"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-push"
echo "  $OUT/gt-afp-meta"
echo
echo "Version marker: 0.9.5-ddp-rfork-r4c"
echo "R4 resource stream: unchanged and hardware-proven"
echo "Authenticated DDP URLs: enabled"
echo "gt-afp-ls interactive-command hint: removed"
echo "Write/FinderInfo/resource validation tools: enabled"
echo "R4C contains no R2B/R2C/R2D/R2E diagnostic overlays."
