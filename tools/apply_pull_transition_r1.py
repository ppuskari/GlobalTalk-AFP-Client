#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Tighten the data-fork -> ResourceFork transition for the native ATP R1
# downloader. Netatalk Client 0.9.5 fetches FinderInfo before it begins the
# ResourceFork transfer. Over classic ASP/DDP that extra AFP round trip is
# visible as a dead spot between forks.
#
# R4 already provides the hardware-proven stateful ResourceFork stream:
# one open, sequential reads, one close. This overlay changes only ordering:
# ResourceFork first, then FinderInfo, then generic xattrs.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PULL FORK TRANSITION R1"


def die(msg):
    raise SystemExit("apply_pull_transition_r1: " + msg)


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


def patch_metadata(path):
    text = read_text(path)

    if MARKER in text:
        return

    signature = "int afp_sl_metadata_copy_remote_to_local("
    start, end = function_span(text, signature)
    func = text[start:end]

    finder_block = (
        "    finder_ret = afp_sl_getfinderinfo(source_volume, source_path, finderinfo,\n"
        "                                      sizeof(finderinfo));\n"
        "\n"
        "    if (finder_ret >= 0 && finder_ret != (int)sizeof(finderinfo)) {\n"
        "        return -EIO;\n"
        "    }\n"
        "\n"
        "    if (finder_ret < 0 && !transfer_error_absent(finder_ret)\n"
        "            && !transfer_error_unsupported(finder_ret)) {\n"
        "        return finder_ret;\n"
        "    }\n"
        "\n"
    )

    count = func.count(finder_block)
    if count != 1:
        die("FinderInfo prefetch block expected once, found {}".format(count))

    func = func.replace(finder_block, "", 1)

    local_apply = "    if (finder_ret == (int)sizeof(finderinfo)) {\n"
    count = func.count(local_apply)
    if count != 1:
        die("FinderInfo local-apply anchor expected once, found {}".format(count))

    delayed_block = (
        "    /* " + MARKER + "\n"
        "     * Keep the post-data-fork wire transition focused on the next fork.\n"
        "     * R4 has already completed the stateful ResourceFork stream here;\n"
        "     * fetch FinderInfo only after that stream closes. */\n"
        "    finder_ret = afp_sl_getfinderinfo(source_volume, source_path, finderinfo,\n"
        "                                      sizeof(finderinfo));\n"
        "\n"
        "    if (finder_ret >= 0 && finder_ret != (int)sizeof(finderinfo)) {\n"
        "        return -EIO;\n"
        "    }\n"
        "\n"
        "    if (finder_ret < 0 && !transfer_error_absent(finder_ret)\n"
        "            && !transfer_error_unsupported(finder_ret)) {\n"
        "        return finder_ret;\n"
        "    }\n"
        "\n"
    )

    func = func.replace(local_apply, delayed_block + local_apply, 1)
    text = text[:start] + func + text[end:]
    write_text(path, text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_pull_transition_r1.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "daemon", "metadata.c")

    if not os.path.isfile(path):
        die("required pinned source missing: {}".format(path))

    patch_metadata(path)
    print("Native ATP pull fork-transition ordering ready: {}".format(root))
    print("  ResourceFork stream now precedes FinderInfo fetch")


if __name__ == "__main__":
    main()
