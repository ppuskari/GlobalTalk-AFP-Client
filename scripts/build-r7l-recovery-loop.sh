#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
BASE="$ROOT/build-r7k-trials"
OUT="$ROOT/build-r7l-recovery-loop"
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
VERSION="0.9.5-ddp-native-atp-r7k-finder-trials"

# Reconstruct the exact R7K/R7J baseline first.  This also leaves the generated
# Netatalk Client tree patched through R7K and produces reusable object files.
sh "$ROOT/scripts/build-r7k-finder-trials.sh"

python3 "$ROOT/tools/apply_datafork_recovery_loop_r7l.py" "$CLIENT"

grep 'GLOBALTALK DATAFORK RECOVERY LOOP R7L' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7L: validation stat transient; retrying recovery' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME IDENTITY R7I.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DEEP RECOVERY R7J' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK FINDER TOLERANCE R7K' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

# R7L only changes cmdline/cmdline_afp.c.  Preserve the known-good R7K build
# artifacts, recompile that one translation unit, then relink gt-afp-pull.
rm -rf "$OUT"
cp -a "$BASE" "$OUT"

CC=${CC:-cc}
CFLAGS="-O2 -g -std=gnu11 -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64"
CFLAGS="$CFLAGS -DAFPCLIENT_INTERNAL"
CFLAGS="$CFLAGS -DNETATALK_CLIENT_VERSION=\"$VERSION\""
CFLAGS="$CFLAGS -DBINDIR=\"$OUT\""
CFLAGS="$CFLAGS -DHAVE_SYS_XATTR_H"

INCLUDES="-I$CLIENT -I$CLIENT/include -I$CLIENT/lib"
INCLUDES="$INCLUDES -I$CLIENT/daemon -I$CLIENT/cmdline"
INCLUDES="$INCLUDES -I$ROOT/legacy -I/usr/local/include"

CMD_OBJ="$OBJ/cmdline_cmdline_afp_c.o"
echo "CC  cmdline/cmdline_afp.c (R7L)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/cmdline/cmdline_afp.c" -o "$CMD_OBJ"

LIBS="$ATPR1 -lpthread -ldl"

echo "LD  $OUT/gt-afp-pull (R7L)"
"$CC" -o "$OUT/gt-afp-pull" \
    "$OBJ/native_atp.o" \
    "$OBJ"/lib_*.o \
    "$OBJ/daemon_stateless_c.o" \
    "$OBJ/daemon_metadata_c.o" \
    "$CMD_OBJ" \
    "$OBJ/legacy_compat.o" \
    "$OBJ/legacy_batch_main.o" \
    $LIBS

strings "$OUT/gt-afp-pull" | grep -F \
    'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L validation-stat retry marker missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7L: DID-prime failed; retrying recovery' >/dev/null || {
    echo "ERROR: R7L DID-prime retry marker missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7J: metadata recovery requested' >/dev/null || {
    echo "ERROR: R7J metadata recovery baseline missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict identity guard missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing control missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'GT_AFP_R7K_ATP_SENDS' >/dev/null || {
    echo "ERROR: R7K ATP retry control missing." >&2
    exit 1
}

python3 -m py_compile "$ROOT/tools/apply_datafork_recovery_loop_r7l.py"
bash -n "$ROOT/scripts/gt-pull-r7l.sh"

echo
echo "R7L data-fork recovery-loop build ready."
echo "Baseline: R7K trial controls + R7J full-tree recovery"
echo "Healthy AFP path: unchanged"
echo "Data-fork recovery budget: 6 total recovery-stage cycles"
echo "Reconnect failure: retries within budget"
echo "DID-prime failure: retries within budget"
echo "Transient validation-stat failure: retries within budget"
echo "Identity mismatch: still immediately fatal"
echo "Resume identity: required nonzero matching CNID + exact fork size"
echo "Recovery-only settle delay: 1 second"
echo "ATP timer: 2 seconds"
echo "ATP sends/pacing: still runtime-selectable through R7K controls"
echo "Output: $OUT"
echo "Final gt-afp-pull binary: R7L markers verified"
echo
echo "Recommended next trial: seven50 (7 sends / 50 ms)"
echo "  ./scripts/gt-afp-reset.sh"
echo "  bash scripts/gt-pull-r7l.sh seven50 'AFP_URL' 'DEST'"
