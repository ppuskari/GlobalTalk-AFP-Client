#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7FB diagnostic: R7FA plus resource-fork length in FPEnumerate/readdir IPC.
# IMPORTANT: the extra value is carried but NOT consumed by metadata copy.
# This isolates the network/packing effect of widening FPEnumerate records.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC"


def die(msg):
    raise SystemExit("apply_diag_r7fb_rsrc_enum: " + msg)


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
    old = '''struct afp_file_info_basic {\n    char name[AFP_MAX_PATH];\n    unsigned int creation_date;\n    unsigned int modification_date;\n    struct afp_unixprivs unixprivs;\n    unsigned long long size;\n};\n'''
    new = '''/* GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC */\nstruct afp_file_info_basic {\n    char name[AFP_MAX_PATH];\n    unsigned int creation_date;\n    unsigned int modification_date;\n    struct afp_unixprivs unixprivs;\n    unsigned long long size;\n    unsigned long long resource_size;\n};\n'''
    return replace_once(text, old, new, "afp_file_info_basic")


def patch_lowlevel(text):
    start, end = function_span(text, "int ll_readdir(")
    func = text[start:end]
    old1 = '''    if (volume->server->using_version->av_number < 30) {\n        filebitmap |= (resource ?\n                  kFPRsrcForkLenBit : kFPDataForkLenBit);\n    } else {\n        filebitmap |= (resource ?\n                  kFPRsrcForkLenBit : kFPExtDataForkLenBit);\n    }\n'''
    old2 = '''    if (volume->server->using_version->av_number < 30) {\n        filebitmap |= (resource ? kFPRsrcForkLenBit : kFPDataForkLenBit);\n    } else {\n        filebitmap |= (resource ? kFPRsrcForkLenBit : kFPExtDataForkLenBit);\n    }\n'''
    new = '''    /* GLOBALTALK R7FB RSRC ENUM DIAGNOSTIC\n     * Diagnostic only: ask for both fork lengths.  No caller consumes the\n     * resource length yet; this measures FPEnumerate widening by itself. */\n    (void)resource;\n    if (volume->server->using_version->av_number < 30) {\n        filebitmap |= kFPDataForkLenBit | kFPRsrcForkLenBit;\n    } else {\n        filebitmap |= kFPExtDataForkLenBit | kFPExtRsrcForkLenBit;\n    }\n'''
    if old1 in func:
        func = func.replace(old1, new, 1)
    elif old2 in func:
        func = func.replace(old2, new, 1)
    else:
        die("ll_readdir fork bitmap block not found")
    return text[:start] + func + text[end:]


def patch_commands(text):
    start, end = function_span(text, "static unsigned char process_readdir(")
    func = text[start:end]
    old = '''        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 2 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t);\n'''
    new = '''        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 2 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t) * 2;\n'''
    func = replace_once(func, old, new, "readdir entry size")
    old = '''        memcpy(p, &fp->size, sizeof(uint64_t));\n        p += sizeof(uint64_t);\n        fp = fp->next;\n'''
    new = '''        memcpy(p, &fp->size, sizeof(uint64_t));\n        p += sizeof(uint64_t);\n        memcpy(p, &fp->resourcesize, sizeof(uint64_t));\n        p += sizeof(uint64_t);\n        fp = fp->next;\n'''
    func = replace_once(func, old, new, "readdir pack resource size")
    return text[:start] + func + text[end:]


def patch_stateless(text):
    start, end = function_span(text, "int afp_sl_readdir(")
    func = text[start:end]
    old = '''                memcpy(&current_basic->size, p, sizeof(uint64_t));\n                p += sizeof(uint64_t);\n                current_basic++;\n'''
    new = '''                memcpy(&current_basic->size, p, sizeof(uint64_t));\n                p += sizeof(uint64_t);\n                memcpy(&current_basic->resource_size, p, sizeof(uint64_t));\n                p += sizeof(uint64_t);\n                current_basic++;\n'''
    func = replace_once(func, old, new, "readdir unpack resource size")
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_diag_r7fb_rsrc_enum.py NETATALK_CLIENT_TREE")
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
        print("R7FB already applied")
        return

    write_text(paths["header"], patch_header(read_text(paths["header"])))
    write_text(paths["lowlevel"], patch_lowlevel(read_text(paths["lowlevel"])))
    write_text(paths["commands"], patch_commands(read_text(paths["commands"])))
    write_text(paths["stateless"], patch_stateless(read_text(paths["stateless"])))

    print("Applied R7FB resource-length enumeration diagnostic")
    print("  inherits R7FA xattr suppression")
    print("  FPEnumerate adds only resource-fork length")
    print("  resource length is carried but NOT consumed")
    print("  FinderInfo lookup remains legacy R7E path")


if __name__ == "__main__":
    main()
