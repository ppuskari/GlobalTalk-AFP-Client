#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
    echo "usage: $0 OBJECT ZONE [VOLUME]" >&2
    exit 2
fi

OBJECT=$1
ZONE=$2
VOLUME=${3:-}

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AFPCMD="$ROOT/work/netatalk-client/build/cmdline/afpcmd"

echo "== NBP =="
nbplkup "${OBJECT}:AFPServer@${ZONE}"

echo
echo "== AFP-over-DDP =="
if [ -n "$VOLUME" ]; then
    URL="afp+ddp://${OBJECT}@${ZONE}/${VOLUME}"
else
    URL="afp+ddp://${OBJECT}@${ZONE}"
fi

echo "URL: $URL"
exec "$AFPCMD" "$URL"
