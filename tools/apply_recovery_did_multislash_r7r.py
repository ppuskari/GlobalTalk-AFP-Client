#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7R: tolerate repeated slash separators in the
# recovery-only R7D DID-prime path walker.
#
# Some recursive paths reach recovery in the canonical form //dir/file.
# R7D skipped exactly one slash, then treated the second slash as an empty
# component and returned -ENAMETOOLONG locally.  Collapse repeated separators
# before parsing each component.  Normal AFP traffic is unchanged.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RECOVERY DID MULTISLASH R7R"
R7D_MARKER = "GLOBALTALK FINDER RECOVERY DID R7D"


def die(msg):
    raise SystemExit("apply_recovery_did_multislash_r7r: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_recovery_did_multislash_r7r.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Recovery DID multislash R7R already applied: {}".format(path))
        return
    if R7D_MARKER not in text:
        die("R7D must be applied first")

    old = '''        if (*scan == '/') {\n            scan++;\n        }\n        if (*scan == '\\0') {\n            break;\n        }\n'''
    new = '''        /* GLOBALTALK RECOVERY DID MULTISLASH R7R\n         * Recursive server paths can legitimately arrive as //dir/file.\n         * Skip every adjacent separator before extracting the next component\n         * so an empty component cannot be misreported as ENAMETOOLONG. */\n        while (*scan == '/') {\n            scan++;\n        }\n        if (*scan == '\\0') {\n            break;\n        }\n'''

    count = text.count(old)
    if count != 1:
        die("expected R7D slash guard once, found {}".format(count))

    text = text.replace(old, new, 1)
    write_text(path, text)

    print("Applied recovery DID multislash R7R: {}".format(path))
    print("  //dir/file and /dir/file now prime the same DID chain")
    print("  normal transfer path unchanged")
    print("  R7I.2 identity validation unchanged")
    print("  R7L six-cycle recovery budget unchanged")


if __name__ == "__main__":
    main()
