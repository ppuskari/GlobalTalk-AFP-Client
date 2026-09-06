#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2c"

if [ ! -f "$CLIENT/lib/afp_url.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# Preserve the proven rooted DDP path semantics from R2A.
python3 "$ROOT/tools/apply_rfork_r2a_path.py" "$CLIENT"

# Keep the metadata-stage diagnostics from R2B.
python3 "$ROOT/tools/apply_rfork_r2b_diag.py" "$CLIENT"

# Add precise ll_read()/FPRead diagnostics.  build-rfork-r2.sh refreshes only
# asp_transport.c; this lowlevel.c instrumentation therefore remains in place
# while the guarded R2 short-read fix is applied/idempotently retained.
python3 "$ROOT/tools/apply_rfork_r2c_read_diag.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2c-diag" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2C
R2A rooted path + R2B metadata diagnostics + exact ll_read/FPRead diagnostics.
EOF

echo
echo "ASP resource-fork R2C diagnostic tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Look for lines beginning: R2B META and R2C READ"
