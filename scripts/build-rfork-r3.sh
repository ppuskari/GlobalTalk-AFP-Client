#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r3"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# R2B-R2E diagnostics intentionally edited generated files under work/.
# Reconstruct a clean production candidate from the pinned nested checkout,
# without resetting or cleaning the parent GlobalTalk-AFP-Client repository.
# Netatalk Client 0.9.5 keeps its stateless public header at include/afpsl.h.
for path in \
    lib/lowlevel.c \
    lib/afp_url.c \
    daemon/metadata.c \
    daemon/commands.c \
    cmdline/cmdline_afp.c \
    cmdline/cmdline_afp.h \
    include/afpsl.h
do
    git -C "$CLIENT" show "HEAD:$path" > "$CLIENT/$path"
done

# Recreate the DDP URL parser directly from clean upstream source using the
# rooted path behavior proven by the PageSpinner R2F hardware test.
python3 "$ROOT/tools/apply_ddp_rooted_url.py" "$CLIENT"

# Backport the upstream AFP 2.x fork-state correction so resource FPOpenFork
# remains a resource fork after FPGetFileDirParms clears afp_file_info.
python3 "$ROOT/tools/apply_rfork_r3_forkstate.py" "$CLIENT"

# Reduce path-based resource-fork reopen/query/close overhead. The pinned
# 0.9.5 stateless payload ceiling is 16384 bytes. ASP still uses the proven
# 4624-byte transaction ceiling internally.
python3 "$ROOT/tools/apply_rfork_r3_batch.py" "$CLIENT"

# The R2 builder owns the proven ASP WRTCONT, eight-packet response handling,
# short-success-not-EOF logic, stateless ASP compatibility, ATP-R1 shim, and
# the explicit AFP-version selector used to probe older servers.
RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r3" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R3
Integrated hardware-proven correctness plus conservative receive batching:
- rooted afp+ddp pathname compatibility
- preserve AFP 2.x resource fork state across pre-open parameter query
- short successful ASP read is not EOF
- ASP resource-fork transport/WRTCONT fixes from R2
- 16 KiB stateless metadata batch; ASP wire quantum remains 4624 bytes
- gt-afp-ls volume and directory browser using the same R3 session path
- explicit AFP version selection: auto, 1.1, 2.0, 2.1, 2.2
EOF

# Production candidate must not accidentally contain the diagnostic overlays.
for binary in gt-afp-pull gt-afp-ls afpsld
do
    if strings "$OUT/$binary" | \
        grep -E 'R2B META|R2C READ|R2D READ|R2E OPEN' >/dev/null 2>&1; then
        echo "ERROR: diagnostic marker leaked into R3 $binary." >&2
        exit 1
    fi
done

strings "$OUT/gt-afp-pull" | grep '0.9.5-ddp-rfork-r3' >/dev/null
strings "$OUT/gt-afp-ls" | grep '0.9.5-ddp-rfork-r3' >/dev/null

if [ -f "$ROOT/tests/test_rfork_r2_model.py" ]; then
    python3 "$ROOT/tests/test_rfork_r2_model.py"
fi
if [ -f "$ROOT/tests/test_rfork_r3_model.py" ]; then
    python3 "$ROOT/tests/test_rfork_r3_model.py"
fi

echo
echo "ASP resource-fork R3 integration tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo "  $OUT/gt-afp-ls"
echo
echo "Version marker: 0.9.5-ddp-rfork-r3"
echo "Metadata batch: 16384 bytes"
echo "ASP response ceiling: 4624 bytes"
echo "AFP version selector: auto, 1.1, 2.0, 2.1, 2.2"
echo "R3 contains no R2B/R2C/R2D/R2E diagnostic overlays."
