#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# PuTTY-friendly Stable R7Q UI shim.
#
# Execute the tested R7Q implementation after applying two presentation-only
# source transforms in memory:
#   1. remove the deliberate 10-second permanent history line;
#   2. clamp live TTY status to the current terminal width so PuTTY cannot
#      soft-wrap a long progress line and advance the scrollback.
#
# No AFP, retry, recovery, metadata, or filesystem behavior is changed.

from __future__ import print_function

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMPL = os.path.join(ROOT, "scripts", "gt-pull-stable-r7q.py")

if not os.path.isfile(IMPL):
    print("Stable R7Q implementation missing: %s" % IMPL, file=sys.stderr)
    sys.exit(1)

with open(IMPL, "r") as handle:
    source = handle.read()

history_block = '''                    if tty and now - last_history >= 10.0:\n                        clear_live(True)\n                        print(status)\n                        last_history = now\n\n'''

if history_block not in source:
    print("R7Q PuTTY shim: expected history block not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)

source = source.replace(history_block, "", 1)

write_block = '''                    if tty:\n                        sys.stdout.write("\\r\\033[K" + status)\n                        sys.stdout.flush()\n                    elif now - last_history >= 5.0:\n'''

write_replacement = '''                    if tty:\n                        try:\n                            columns = shutil.get_terminal_size((160, 24)).columns\n                        except Exception:\n                            columns = 160\n                        if columns > 8 and len(status) >= columns:\n                            status = status[:columns - 2] + ">"\n                        sys.stdout.write("\\r\\033[K" + status)\n                        sys.stdout.flush()\n                    elif now - last_history >= 5.0:\n'''

if write_block not in source:
    print("R7Q PuTTY shim: expected live-write block not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)

source = source.replace(write_block, write_replacement, 1)

code = compile(source, IMPL, "exec")
globals_dict = {
    "__name__": "__main__",
    "__file__": IMPL,
    "__package__": None,
}
exec(code, globals_dict)
