#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2a"

if [ ! -f "$CLIENT/lib/afp_url.c" ]; then
    echo "Patched Netatalk Client tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# R2A restores exactly one proven behavior from the saved pre-R2 Jessie tree:
# afp+ddp URL paths presented to Netatalk Client start with '/'.  Do this
# before the normal R2 compile pipeline.  All ASP/resource-fork R2 code stays
# unchanged; only URL path normalization differs.
python3 "$ROOT/tools/apply_rfork_r2a_path.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2a" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2A
R2 baseline plus rooted afp+ddp path compatibility fix.
EOF

echo
echo "ASP resource-fork R2A test tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "R2A delta: rooted afp+ddp path restored from pre-R2 Jessie tree"
