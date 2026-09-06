#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2b"

if [ ! -f "$CLIENT/lib/afp_url.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Preserve the proven R2A rooted DDP path fix, then add read-only diagnostics
# around Netatalk Client 0.9.5's remote->local metadata copy.  The underlying
# R2 transport and short-success read fixes remain unchanged.
python3 "$ROOT/tools/apply_rfork_r2a_path.py" "$CLIENT"
python3 "$ROOT/tools/apply_rfork_r2b_diag.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2b-diag" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2B diagnostic
R2A rooted DDP path plus metadata resource-fork stage diagnostics.
EOF

echo
echo "ASP resource-fork R2B diagnostic tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Look for lines beginning: R2B META"
