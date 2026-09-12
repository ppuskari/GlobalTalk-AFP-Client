#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7I.1: use AFP NodeID/CNID + fork size for resume
# identity across reconnects. AFP 2.x timestamp normalization can legitimately
# shift reported mtimes when a new session recalculates server clock offset.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RESUME IDENTITY R7I.1"


def die(msg):
    raise SystemExit("apply_resume_identity_r7i1: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_resume_identity_r7i1.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Resume identity R7I.1 already applied: {}".format(path))
        return
    if "GLOBALTALK RESUME DATAFORK R7I" not in text:
        die("R7I must be applied first")

    old = '''        if (fresh_stat.st_size != expected_stat.st_size\n                || fresh_stat.st_mtime != expected_stat.st_mtime) {\n            printf("R7I: resume validation mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-mtime=%lld fresh-mtime=%lld\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (long long)expected_stat.st_mtime,\n                   (long long)fresh_stat.st_mtime);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n'''

    new = '''        /* GLOBALTALK RESUME IDENTITY R7I.1\n         * Netatalk maps AFP NodeID/CNID to st_ino.  That namespace identity\n         * is stable across reconnects, while AFP 2.x mtime can move when the\n         * new session recalculates server clock offset.  Require same fork\n         * size and, when available, the same CNID.  Treat mtime drift only as\n         * a diagnostic. */\n        if (fresh_stat.st_size != expected_stat.st_size\n                || (expected_stat.st_ino != 0 && fresh_stat.st_ino != 0\n                    && fresh_stat.st_ino != expected_stat.st_ino)) {\n            printf("R7I: resume identity mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-cnid=%llu fresh-cnid=%llu\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (unsigned long long)expected_stat.st_ino,\n                   (unsigned long long)fresh_stat.st_ino);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n        if (fresh_stat.st_mtime != expected_stat.st_mtime) {\n            printf("R7I.1: resume mtime drift ignored path=%s "\n                   "expected-mtime=%lld fresh-mtime=%lld delta=%lld\\n",\n                   path,\n                   (long long)expected_stat.st_mtime,\n                   (long long)fresh_stat.st_mtime,\n                   (long long)fresh_stat.st_mtime\n                       - (long long)expected_stat.st_mtime);\n        }\n'''

    text = replace_once(text, old, new, "resume identity validation")

    old_pass = '''        printf("R7I: resume validation passed path=%s offset=%llu size=%llu mtime=%lld\\n",\n               path, total,\n               (unsigned long long)expected_stat.st_size,\n               (long long)expected_stat.st_mtime);\n'''
    new_pass = '''        printf("R7I: resume validation passed path=%s offset=%llu "\n               "size=%llu cnid=%llu\\n",\n               path, total,\n               (unsigned long long)expected_stat.st_size,\n               (unsigned long long)expected_stat.st_ino);\n'''
    text = replace_once(text, old_pass, new_pass, "resume validation log")

    write_text(path, text)
    print("Applied resume identity R7I.1: {}".format(path))
    print("  identity: AFP NodeID/CNID (st_ino) + data-fork size")
    print("  reconnect mtime drift is diagnostic only")
    print("  if CNID is unavailable, exact size remains mandatory")
    print("  data-fork resume offsets and recovery budget unchanged")


if __name__ == "__main__":
    main()
