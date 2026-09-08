#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2d"

if [ ! -f "$CLIENT/lib/afp_url.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Preserve the proven rooted DDP path semantics from R2A.
python3 "$ROOT/tools/apply_rfork_r2a_path.py" "$CLIENT"

# Keep the metadata-stage diagnostics from R2B.
python3 "$ROOT/tools/apply_rfork_r2b_diag.py" "$CLIENT"

# Instrument ll_read(), then redirect those daemon-side diagnostics to the
# caller-selected GT_R2_READ_LOG file.
python3 "$ROOT/tools/apply_rfork_r2c_read_diag.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2d_daemon_log.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2d-diag" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2D
R2A rooted path + R2B metadata diagnostics + daemon-side ll_read/FPRead log.
EOF

echo
echo "ASP resource-fork R2D diagnostic tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Set GT_R2_READ_LOG to a writable path before running gt-afp-pull."
