#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2e"

if [ ! -f "$CLIENT/lib/afp_url.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

python3 "$ROOT/tools/apply_rfork_r2a_path.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2b_diag.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2c_read_diag.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2d_daemon_log.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2e_open_diag.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2e-diag" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2E
R2A rooted path + metadata/read diagnostics + AFP2 pre-open/FPOpenFork diagnostics.
EOF

echo
echo "ASP resource-fork R2E diagnostic tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Set GT_R2_READ_LOG to a writable path before running gt-afp-pull."
echo "Look for R2E OPEN, R2D READ, and R2B META lines."
