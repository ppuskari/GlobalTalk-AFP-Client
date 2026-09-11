#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7B: reuse caller/enumeration metadata.
#
# Recursive download already receives size/mode/time information from
# FPEnumerate and constructs a struct stat before calling retrieve_file().
# Direct get also stats the object before calling retrieve_file().  The
# historical retrieve_file() then issued a second path-based afp_sl_stat().
#
# A System 7.6 Finder-style walk should consume directory-enumeration results
# rather than immediately re-query every child by full path.  Apart from an
# unnecessary AFP round trip, that second lookup can fail on classic servers
# even though the object was just returned by enumeration.  R7B removes only
# that redundant stat.  Open/read/close behavior, ATP/ASP transport, resource
# forks, metadata copying, and R6 recovery remain unchanged.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK FINDER ENUM METADATA R7B"
R64_MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4"
R7A_MARKER = "GLOBALTALK FINDER ATP RETRY R7A"


def die(msg):
    raise SystemExit("apply_finder_enum_metadata_r7b: " + msg)


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

    old = '''    op_ret = afp_sl_stat(&vol_id, path, NULL, stat);\n    if (op_ret != 0) {\n        printf("R6.1: stat failed path=%s ret=%d\\n", path, op_ret);\n        goto recover_or_out;\n    }\n\n'''

    new = '''    /* GLOBALTALK FINDER ENUM METADATA R7B\n     * The caller already has authoritative metadata: recursive pulls use the\n     * immediately preceding FPEnumerate result, while direct pulls stat once\n     * before entering retrieve_file().  Do not perform a second path lookup. */\n    if (!stat) {\n        op_ret = -EINVAL;\n        printf("R7B: missing caller metadata path=%s ret=%d\\n",\n               path, op_ret);\n        goto recover_or_out;\n    }\n    if (verbose_mode && attempt == 0) {\n        printf("R7B: reusing caller/enumeration metadata path=%s size=%llu\\n",\n               path, (unsigned long long)stat->st_size);\n    }\n\n'''

    count = func.count(old)
    if count != 1:
        die("redundant retrieve stat guard: expected once, found {}".format(count))
    func = func.replace(old, new, 1)

    old_open = '''    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);\n    if (op_ret != 0) {\n        printf("R6.1: open failed path=%s ret=%d\\n", path, op_ret);\n        goto recover_or_out;\n    }\n'''

    new_open = '''    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);\n    if (op_ret != 0) {\n        printf("R6.1: open failed path=%s ret=%d\\n", path, op_ret);\n        if (op_ret == -ENOENT) {\n            printf("R7B: enumerated object could not be reopened by full path: %s\\n",\n                   path);\n        }\n        goto recover_or_out;\n    }\n'''

    count = func.count(old_open)
    if count != 1:
        die("open diagnostic guard: expected once, found {}".format(count))
    func = func.replace(old_open, new_open, 1)

    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_finder_enum_metadata_r7b.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    cmdline = os.path.join(root, "cmdline", "cmdline_afp.c")
    asp = os.path.join(root, "lib", "asp_transport.c")

    if not os.path.isfile(cmdline) or not os.path.isfile(asp):
        die("patched Netatalk Client tree not found: {}".format(root))

    text = read_text(cmdline)
    asp_text = read_text(asp)

    if MARKER in text:
        print("Finder enumeration metadata R7B already applied: {}".format(cmdline))
        return

    if R64_MARKER not in text:
        die("R6.4 must be applied first")
    if R7A_MARKER not in asp_text:
        die("R7A must be applied first")

    text = patch_retrieve(text)
    write_text(cmdline, text)

    print("Applied Finder enumeration metadata R7B: {}".format(cmdline))
    print("  redundant per-file afp_sl_stat removed")
    print("  FPEnumerate/caller size and POSIX metadata reused")
    print("  direct get still performs its initial stat before retrieve_file")
    print("  open/read/close behavior unchanged")
    print("  ENOENT on open is diagnosed as enumerate/path mismatch")
    print("  ATP/ASP transport and R7A retry budget unchanged")


if __name__ == "__main__":
    main()
