#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# R7Q supersedes the R7P-only UI build.  Keep this historical command as a
# compatibility entrypoint so an operator cannot accidentally rebuild a
# progress-only binary and lose retry-safe existing-file handling.
exec sh "$ROOT/scripts/build-stable-r7q-ui.sh"
