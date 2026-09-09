#!/bin/sh
set -eu

USER_NAME=${USER:-$(id -un)}
FORCE=0

if [ "${1:-}" = "--force" ]; then
    FORCE=1
elif [ "$#" -ne 0 ]; then
    echo "Usage:" >&2
    echo "  $0" >&2
    echo "  $0 --force" >&2
    exit 2
fi

ACTIVE=""
for NAME in \
    gt-afp-pull \
    gt-afp-push \
    gt-afp-ls \
    gt-afp-meta
do
    PIDS=$(pgrep -u "$USER_NAME" -x "$NAME" 2>/dev/null || true)

    if [ -n "$PIDS" ]; then
        ACTIVE="${ACTIVE}${NAME}: ${PIDS}
"
    fi
done

if [ -n "$ACTIVE" ] && [ "$FORCE" -ne 1 ]; then
    echo "REFUSING to reset afpsld." >&2
    echo >&2
    echo "Active AFP client process(es) exist:" >&2
    printf "%s" "$ACTIVE" >&2
    echo >&2
    echo "Wait for them to finish." >&2
    echo "Use --force only when disruption is intentional." >&2
    exit 1
fi

if [ -n "$ACTIVE" ]; then
    echo "WARNING: forcing daemon reset with active clients:"
    printf "%s" "$ACTIVE"
    echo
fi

if ! pgrep -u "$USER_NAME" -x afpsld >/dev/null 2>&1; then
    echo "No afpsld process is running."
    exit 0
fi

echo "Stopping afpsld..."
pkill -u "$USER_NAME" -x afpsld 2>/dev/null || true

COUNT=0

while pgrep -u "$USER_NAME" -x afpsld >/dev/null 2>&1
do
    COUNT=$((COUNT + 1))

    if [ "$COUNT" -ge 5 ]; then
        echo "ERROR: afpsld did not exit." >&2
        echo "No SIGKILL was sent." >&2
        exit 1
    fi

    sleep 1
done

echo "afpsld stopped."
echo "The next AFP client will start a fresh daemon."
