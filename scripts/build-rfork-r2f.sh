#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
OUT="$ROOT/build-rfork-r2f"

if [ ! -d "$CLIENT/.git" ]; then
    echo "Pinned Netatalk Client work tree not found." >&2
    echo "Run first: sh scripts/bootstrap-linux.sh" >&2
    exit 1
fi

# R2C/R2D/R2E deliberately instrumented generated source files in work/.
# R2F is the first real correctness target after diagnosis, so refresh the
# files those diagnostics touched from the pinned nested HEAD. afp_url.c is
# also refreshed, then its GlobalTalk afp+ddp parser is rebuilt explicitly
# below; that parser is our overlay, not upstream Netatalk Client source.
# None of this modifies the parent GlobalTalk-AFP-Client repository.
git -C "$CLIENT" show HEAD:lib/lowlevel.c > "$CLIENT/lib/lowlevel.c"
git -C "$CLIENT" show HEAD:lib/afp_url.c > "$CLIENT/lib/afp_url.c"
git -C "$CLIENT" show HEAD:daemon/metadata.c > "$CLIENT/daemon/metadata.c"
git -C "$CLIENT" show HEAD:daemon/commands.c > "$CLIENT/daemon/commands.c"

# Recreate the GlobalTalk DDP URL parser directly from clean pinned source,
# with the pre-R2 Jessie-proven leading '/' behavior already included.
python3 "$ROOT/tools/apply_rfork_r2f_ddp_url.py" "$CLIENT"

# Apply the upstream-proven AFP 2.x fork-state correction before the normal R2
# patcher adds the short-success-not-EOF and ASP resource-fork transport fixes.
python3 "$ROOT/tools/apply_rfork_r2f_forkstate.py" "$CLIENT"

RFORK_OUT="$OUT" \
RFORK_VERSION="0.9.5-ddp-rfork-r2f" \
    sh "$ROOT/scripts/build-rfork-r2.sh"

cat > "$OUT/BUILD-ID.txt" <<'EOF'
GlobalTalk AFP Client ASP Resource Fork R2F
Clean correctness target:
- rooted afp+ddp pathname compatibility
- preserve AFP 2.x resource fork state across pre-open parameter query
- short successful ASP read is not EOF
- ASP resource-fork transport fixes from R2
EOF

echo
echo "ASP resource-fork R2F correctness tools ready:"
echo "  $OUT/afpsld"
echo "  $OUT/gt-afp-pull"
echo
echo "Version marker: 0.9.5-ddp-rfork-r2f"
echo "R2F contains no R2B/R2C/R2D/R2E diagnostic overlays."
