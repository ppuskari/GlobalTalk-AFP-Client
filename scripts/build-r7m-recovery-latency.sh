#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLIENT="$ROOT/work/netatalk-client"
BASE="$ROOT/build-r7l-recovery-loop"
OUT="$ROOT/build-r7m-latency"
OBJ="$OUT/obj"
ATPR1="$ROOT/legacy/atalk-r1/libatalk-atp-r1.a"
VERSION="0.9.5-ddp-native-atp-r7k-finder-trials"

# Reconstruct the exact proven R7L / 7-send-capable baseline first.
sh "$ROOT/scripts/build-r7l-recovery-loop.sh"

python3 "$ROOT/tools/apply_recovery_latency_r7m.py" "$CLIENT"

grep 'GLOBALTALK RECOVERY LATENCY R7M' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GT_AFP_R7M_SKIP_POISON_CLOSE' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7M: stage=best-effort-close' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'R7M: stage=recovery-cycle-ready' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK DATAFORK RECOVERY LOOP R7L' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null
grep 'GLOBALTALK RESUME IDENTITY R7I.2' \
    "$CLIENT/cmdline/cmdline_afp.c" >/dev/null

# R7M changes only cmdline/cmdline_afp.c. Preserve the proven R7L objects and
# relink gt-afp-pull after recompiling that one translation unit.
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
echo "CC  cmdline/cmdline_afp.c (R7M)"
"$CC" $CFLAGS $INCLUDES \
    -include "$ROOT/legacy/legacy_compat.h" \
    -c "$CLIENT/cmdline/cmdline_afp.c" -o "$CMD_OBJ"

LIBS="$ATPR1 -lpthread -ldl"

echo "LD  $OUT/gt-afp-pull (R7M)"
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
    'GT_AFP_R7M_SKIP_POISON_CLOSE' >/dev/null || {
    echo "ERROR: R7M fast-close runtime control missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7M: stage=best-effort-close' >/dev/null || {
    echo "ERROR: R7M close timing marker missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7M: stage=recover-session' >/dev/null || {
    echo "ERROR: R7M reconnect timing marker missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7M: stage=first-resumed-read' >/dev/null || {
    echo "ERROR: R7M resumed-read timing marker missing." >&2
    exit 1
}
strings "$OUT/gt-afp-pull" | grep -F \
    'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery-loop baseline missing." >&2
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

python3 -m py_compile "$ROOT/tools/apply_recovery_latency_r7m.py"
bash -n "$ROOT/scripts/gt-pull-r7m.sh"

echo
echo "R7M recovery-latency build ready."
echo "Baseline: proven R7L reliability state machine"
echo "Recommended transport: 7 total sends / 2-second ATP timer"
echo "Recommended pacing: 50 ms post-object"
echo "timed mode: exact R7L recovery behavior + timing only"
echo "fastclose mode: skip poisoned old-session best-effort close"
echo "Healthy successful FPClose: unchanged in both modes"
echo "R7L recovery budget: 6 cycles"
echo "R7I.2 CNID + exact-size resume guard: unchanged"
echo "Instrumented stages: failed open/read, poisoned close, reconnect,"
echo "  settle, DID-prime, validation stat, local reposition, reopen,"
echo "  first resumed read, total recovery cycle"
echo "Output: $OUT"
echo "Final gt-afp-pull binary: R7M markers verified"
echo
echo "First run should be instrumentation-only control:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  bash scripts/gt-pull-r7m.sh timed 'AFP_URL' 'DEST'"
echo
echo "Then reset and A/B the isolated fix:"
echo "  ./scripts/gt-afp-reset.sh"
echo "  bash scripts/gt-pull-r7m.sh fastclose 'AFP_URL' 'DEST'"
