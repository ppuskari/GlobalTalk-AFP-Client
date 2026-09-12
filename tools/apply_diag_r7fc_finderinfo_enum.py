#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7FC diagnostic: R7FB plus FinderInfo in FPEnumerate/readdir IPC.
# IMPORTANT: FinderInfo is carried but NOT consumed by metadata copy.
# This isolates the incremental effect of adding FinderInfo to the widened
# enumeration record.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK R7FC FINDERINFO ENUM DIAGNOSTIC"
R7FB_MARKER = "GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC"


def die(msg):
    raise SystemExit("apply_diag_r7fc_finderinfo_enum: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected once, found {}".format(what, count))
    return text.replace(old, new, 1)


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


def patch_header(text):
    if R7FB_MARKER not in text:
        die("R7FB must be applied first")
    old = '''    unsigned long long size;\n    unsigned long long resource_size;\n};\n'''
    new = '''    unsigned long long size;\n    unsigned long long resource_size;\n    /* GLOBALTALK R7FC FINDERINFO ENUM DIAGNOSTIC */\n    unsigned char finderinfo[32];\n};\n'''
    return replace_once(text, old, new, "afp_file_info_basic FinderInfo")


def patch_lowlevel(text):
    start, end = function_span(text, "int ll_readdir(")
    func = text[start:end]
    anchor = '''    /* GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC\n     * Diagnostic only: ask for both fork lengths.  No caller consumes the\n     * resource length yet; this measures FPEnumerate widening by itself. */\n'''
    if anchor not in func:
        die("R7FB ll_readdir marker not found")
    insertion = anchor + '''    /* GLOBALTALK R7FC FINDERINFO ENUM DIAGNOSTIC\n     * Add FinderInfo only; callers still use the legacy metadata lookup. */\n    filebitmap |= kFPFinderInfoBit;\n'''
    func = func.replace(anchor, insertion, 1)
    return text[:start] + func + text[end:]


def patch_commands(text):
    start, end = function_span(text, "static unsigned char process_readdir(")
    func = text[start:end]
    old = '''        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 2 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t) * 2;\n'''
    new = '''        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 2 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t) * 2 + 32U;\n'''
    func = replace_once(func, old, new, "readdir FinderInfo entry size")
    old = '''        memcpy(p, &fp->resourcesize, sizeof(uint64_t));\n        p += sizeof(uint64_t);\n        fp = fp->next;\n'''
    new = '''        memcpy(p, &fp->resourcesize, sizeof(uint64_t));\n        p += sizeof(uint64_t);\n        memcpy(p, fp->finderinfo, 32U);\n        p += 32U;\n        fp = fp->next;\n'''
    func = replace_once(func, old, new, "readdir pack FinderInfo")
    return text[:start] + func + text[end:]


def patch_stateless(text):
    start, end = function_span(text, "int afp_sl_readdir(")
    func = text[start:end]
    old = '''                memcpy(&current_basic->resource_size, p, sizeof(uint64_t));\n                p += sizeof(uint64_t);\n                current_basic++;\n'''
    new = '''                memcpy(&current_basic->resource_size, p, sizeof(uint64_t));\n                p += sizeof(uint64_t);\n                memcpy(current_basic->finderinfo, p, 32U);\n                p += 32U;\n                current_basic++;\n'''
    func = replace_once(func, old, new, "readdir unpack FinderInfo")
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_diag_r7fc_finderinfo_enum.py NETATALK_CLIENT_TREE")
    root = os.path.abspath(sys.argv[1])
    paths = {
        "header": os.path.join(root, "include", "afpsl.h"),
        "lowlevel": os.path.join(root, "lib", "lowlevel.c"),
        "commands": os.path.join(root, "daemon", "commands.c"),
        "stateless": os.path.join(root, "daemon", "stateless.c"),
    }
    for path in paths.values():
        if not os.path.isfile(path):
            die("missing {}".format(path))

    if MARKER in read_text(paths["header"]):
        print("R7FC already applied")
        return

    write_text(paths["header"], patch_header(read_text(paths["header"])))
    write_text(paths["lowlevel"], patch_lowlevel(read_text(paths["lowlevel"])))
    write_text(paths["commands"], patch_commands(read_text(paths["commands"])))
    write_text(paths["stateless"], patch_stateless(read_text(paths["stateless"])))

    print("Applied R7FC FinderInfo enumeration diagnostic")
    print("  inherits R7FA xattr suppression")
    print("  inherits R7FB resource-length field")
    print("  FPEnumerate additionally requests FinderInfo")
    print("  FinderInfo is carried but NOT consumed")
    print("  metadata lookup behavior remains legacy R7E")


if __name__ == "__main__":
    main()
