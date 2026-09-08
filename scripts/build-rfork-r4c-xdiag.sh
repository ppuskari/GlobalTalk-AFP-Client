#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OVERLAY="$ROOT/overlay/lib/asp_transport.c"
TMPROOT=$(mktemp -d /tmp/gt-afp-r4c-xdiag.XXXXXX)
BACKUP="$TMPROOT/asp_transport.c.orig"

cleanup()
{
    if [ -f "$BACKUP" ]; then
        cp "$BACKUP" "$OVERLAY"
    fi
    rm -rf "$TMPROOT"
}
trap cleanup EXIT HUP INT TERM

cp "$OVERLAY" "$BACKUP"
mkdir -p "$TMPROOT/work/lib"
cp "$OVERLAY" "$TMPROOT/work/lib/asp_transport.c"

python3 "$ROOT/tools/apply_asp_xact_diag.py" "$TMPROOT/work"
cp "$TMPROOT/work/lib/asp_transport.c" "$OVERLAY"

# build-rfork-r2.sh refreshes work/lib/asp_transport.c from the tracked overlay
# before layering R2.  Temporarily patching the overlay therefore places the
# diagnostic below R2 without changing the checked-in production source.  The
# EXIT trap restores the overlay immediately after the build.
sh "$ROOT/scripts/build-rfork-r4c.sh"

echo
echo "R4C ASP transaction diagnostic build ready."
echo "Temporary source overlay restored to repository version."
echo "Diagnostic file: /tmp/gt-afp-r4c-asp-xact.log"
