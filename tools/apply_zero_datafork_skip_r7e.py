#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7E: skip remote data-fork I/O when FPEnumerate/stat
# already reports an exact zero-byte data fork.
#
# Classic Mac archives contain many resource-fork-only files.  R7B already
# trusts caller/enumeration size metadata and verifies nonzero data forks
# against that size.  Opening, reading EOF, and closing a data fork whose known
# size is zero adds three unnecessary AFP operations per object and increases
# command pressure on old System 7 servers.
#
# R7E leaves creation of the local zero-byte file intact, then returns success
# from retrieve_file() before FPOpenFork/FPRead/FPClose.  The existing metadata
# stage still copies FinderInfo, the resource fork, xattrs/AppleDouble, mode,
# and timestamps exactly as before.
#
# ATP/ASP transport and all nonzero data-fork behavior are unchanged.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK ZERO DATAFORK SKIP R7E"
R7D_MARKER = "GLOBALTALK FINDER RECOVERY DID R7D"


def die(msg):
    raise SystemExit("apply_zero_datafork_skip_r7e: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def function_span(text, signature):
    start = text.find(signature)
    if start < 0:
        die("function not found: {}".format(signature))
    brace = text.find("{", start)
    if brace < 0:
        die("opening brace not found: {}".format(signature))

    depth = 0
    i = brace
    state = "code"
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if c == '"':
                state = "string"
            elif c == "'":
                state = "char"
            elif c == "/" and n == "/":
                state = "linecomment"
                i += 1
            elif c == "/" and n == "*":
                state = "blockcomment"
                i += 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return start, i + 1
        elif state == "string":
            if c == "\\":
                i += 1
            elif c == '"':
                state = "code"
        elif state == "char":
            if c == "\\":
                i += 1
            elif c == "'":
                state = "code"
        elif state == "linecomment":
            if c == "\n":
                state = "code"
        elif state == "blockcomment":
            if c == "*" and n == "/":
                state = "code"
                i += 1
        i += 1

    die("unterminated function: {}".format(signature))


def patch_retrieve(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]

    old = '''    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);\n'''
    new = '''    /* GLOBALTALK ZERO DATAFORK SKIP R7E\n     * FPEnumerate/direct stat already established an exact empty data fork.\n     * The caller has created/truncated the local data file.  Skip the remote\n     * fork open/read/close entirely; FinderInfo/resource fork metadata is\n     * copied by the unchanged metadata stage after retrieve_file returns. */\n    if (stat && stat->st_size == 0) {\n        if (verbose_mode) {\n            printf("R7E: empty data fork; skipping AFP open/read/close path=%s\\n",\n                   path);\n            printf("    Transferred 0 bytes (empty data fork; no AFP data-fork I/O)\\n");\n        }\n        *amount_written = 0;\n        ret = 0;\n        goto out;\n    }\n\n    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);\n'''

    count = func.count(old)
    if count != 1:
        die("retrieve open guard: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_zero_datafork_skip_r7e.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    cmdline = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(cmdline):
        die("missing {}".format(cmdline))

    text = read_text(cmdline)
    if MARKER in text:
        print("Zero data-fork skip R7E already applied: {}".format(cmdline))
        return
    if R7D_MARKER not in text:
        die("R7D must be applied first")
    if "GLOBALTALK FINDER ENUM METADATA R7B" not in text:
        die("R7B must be applied first")

    text = patch_retrieve(text)
    write_text(cmdline, text)

    print("Applied zero data-fork skip R7E: {}".format(cmdline))
    print("  known zero-byte data forks skip AFP open/read/close")
    print("  local zero-byte file creation remains unchanged")
    print("  FinderInfo/resource-fork/AppleDouble metadata still copied")
    print("  nonzero data-fork behavior and exact-size verification unchanged")
    print("  ATP/ASP transport and retry budgets unchanged")


if __name__ == "__main__":
    main()
