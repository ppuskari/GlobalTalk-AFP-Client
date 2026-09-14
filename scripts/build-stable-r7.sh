#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE="$ROOT/build-r7m-latency"
OUT="$ROOT/build-stable-r7"

# Reconstruct the proven R7M/R7L binary set.  Stable R7 changes no AFP C
# behavior; the stable 7-send / 50-ms policy is applied by the user-facing
# wrappers at runtime.
sh "$ROOT/scripts/build-r7m-recovery-latency.sh"

rm -rf "$OUT"
cp -a "$BASE" "$OUT"

PULL="$OUT/gt-afp-pull"
LS="$OUT/gt-afp-ls"
AFPSLD="$OUT/afpsld"

for FILE in "$PULL" "$LS" "$AFPSLD"; do
    test -x "$FILE" || {
        echo "ERROR: stable component missing: $FILE" >&2
        exit 1
    }
done

strings "$PULL" | grep -F 'R7L: validation stat transient; retrying recovery' >/dev/null || {
    echo "ERROR: R7L recovery loop missing from stable puller." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7I.2: resume identity mismatch' >/dev/null || {
    echo "ERROR: R7I.2 strict resume identity guard missing." >&2
    exit 1
}
strings "$PULL" | grep -F 'R7M: stage=recover-session' >/dev/null || {
    echo "ERROR: R7M timing instrumentation missing." >&2
    exit 1
}
strings "$AFPSLD" | grep -F 'GT_AFP_R7K_ATP_SENDS' >/dev/null || {
    echo "ERROR: R7K ATP-send runtime control missing from afpsld." >&2
    exit 1
}
strings "$PULL" | grep -F 'GT_AFP_R7K_INTERFILE_MS' >/dev/null || {
    echo "ERROR: R7K pacing control missing from puller." >&2
    exit 1
}

python3 -m py_compile "$ROOT/scripts/gt-pull-stable.py"
python3 -m py_compile "$ROOT/scripts/gt-pull-stable-total.py"
python3 -m py_compile "$ROOT/scripts/gt-afp-browser.py"
sh -n "$ROOT/scripts/gt-afp-browser.sh"

echo
echo "GlobalTalk AFP Client Stable R7 build ready."
echo "Profile:              7 total ATP sends"
echo "ATP retry timer:      2 seconds"
echo "Post-object pacing:   50 ms"
echo "Data recovery:        R7L bounded six-cycle state machine"
echo "Resume identity:      R7I.2 nonzero CNID + exact fork size"
echo "Recovery timing:      R7M retained for diagnostics"
echo "Poison-close skip:    disabled"
echo "Whole-tree progress:  optional lightweight catalog preflight"
echo "Default destination:  /mnt/AFPSERVER/128G2/AFPFILES2"
echo "Interactive browser:  scripts/gt-afp-browser.sh"
echo "Direct pull:          scripts/gt-pull-stable.py"
echo "Output:               $OUT"
