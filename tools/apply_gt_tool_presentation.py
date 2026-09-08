#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Presentation-only cleanup for the non-interactive GlobalTalk wrappers.
#
# Pinned Netatalk Client 0.9.5's cmdline setup path assumes the caller is the
# interactive afpcmd shell and prints:
#
#   Use 'ls' to list available volumes, 'cd' to attach to a volume
#
# gt-afp-ls is deliberately a one-shot browser and has no interactive ls/cd
# command loop.  Suppress that inherited hint; gt-afp-ls immediately calls
# com_dir("") and prints the actual volumes/directories itself.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK NONINTERACTIVE TOOL PRESENTATION"


def die(msg):
    raise SystemExit("apply_gt_tool_presentation: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_gt_tool_presentation.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")

    if not os.path.isfile(path):
        die("required pinned source missing: {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("GlobalTalk non-interactive presentation already applied")
        return

    old = '''    } else {\n        printf("Use 'ls' to list available volumes, 'cd' to attach to a volume\\n");\n    }\n'''
    new = '''    } else {\n        /* GLOBALTALK NONINTERACTIVE TOOL PRESENTATION\n         * gt-afp-ls immediately lists volumes itself; do not advertise the\n         * interactive afpcmd ls/cd commands that this wrapper does not have. */\n    }\n'''

    count = text.count(old)
    if count != 1:
        die("expected inherited afpcmd hint once, found {}".format(count))

    text = text.replace(old, new, 1)
    write_text(path, text)

    print("GlobalTalk non-interactive tool presentation ready: {}".format(path))


if __name__ == "__main__":
    main()
