#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7FA diagnostic: keep R7E traffic exactly as-is except suppress the
# post-fork generic xattr enumeration/copy phase for remote->local metadata.
# FinderInfo and resource forks remain on their legacy R7E/R4 paths.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK R7FA XATTR SKIP DIAGNOSTIC"


def die(msg):
    raise SystemExit("apply_diag_r7fa_xattr_skip: " + msg)


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
        die("opening brace not found")
    depth = 0
    state = "code"
    i = brace
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
    die("unterminated function")


def main():
    if len(sys.argv) != 2:
        die("usage: apply_diag_r7fa_xattr_skip.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "daemon", "metadata.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("R7FA already applied")
        return

    start, end = function_span(text, "int afp_sl_metadata_copy_remote_to_local(")
    func = text[start:end]
    old = '''    return transfer_remote_xattrs_to_local(source_volume, source_path,\n                                           local_path, mode, warnings);\n'''
    new = '''    /* GLOBALTALK R7FA XATTR SKIP DIAGNOSTIC\n     * Diagnostic only: classic AFP2/native AppleTalk torture path.  Preserve\n     * FinderInfo and resource-fork handling exactly as R7E/R4, but do not run\n     * the generic xattr list/get stage after each object. */\n    return 0;\n'''
    count = func.count(old)
    if count != 1:
        die("remote->local xattr tail: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    text = text[:start] + func + text[end:]
    write_text(path, text)

    print("Applied R7FA xattr-skip diagnostic")
    print("  FPEnumerate record: unchanged from R7E")
    print("  FinderInfo path: unchanged")
    print("  resource-fork path: unchanged")
    print("  generic remote xattr stage: skipped")


if __name__ == "__main__":
    main()
