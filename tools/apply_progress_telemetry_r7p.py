#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7P operator progress telemetry.
#
# This patch does not change AFP request/retry/recovery behavior.  It emits
# byte counters already known by the successful data-fork and resource-fork
# read loops when GT_AFP_PROGRESS_TELEMETRY=1.  The user-facing progress
# wrapper consumes these markers instead of inferring transfer progress from
# local file lengths, which can be misleading for AppleDouble/resource writes.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PROGRESS TELEMETRY R7P"


def die(msg):
    raise SystemExit("apply_progress_telemetry_r7p: " + msg)


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


def enabled_helper(name):
    return r'''/* GLOBALTALK PROGRESS TELEMETRY R7P */
static int %s(void)
{
    const char *value = getenv("GT_AFP_PROGRESS_TELEMETRY");
    return value && strcmp(value, "1") == 0;
}

''' % name


def patch_cmdline(path):
    text = read_text(path)
    if MARKER in text:
        return
    if "GLOBALTALK RECOVERY LATENCY R7M" not in text:
        die("R7M cmdline baseline missing")

    sig = "static int retrieve_file("
    start, end = function_span(text, sig)
    func = text[start:end]

    old = """        total += received;\n        offset += received;\n"""
    new = r'''        total += received;
        offset += received;
        if (r7p_progress_enabled()) {
            printf("R7P: data path=%s delta=%u total=%llu expected=%llu\n",
                   path, received, total,
                   (unsigned long long)expected_stat.st_size);
            fflush(stdout);
        }
'''
    if func.count(old) != 1:
        die("cmdline data progress guard count={}".format(func.count(old)))
    func = func.replace(old, new, 1)
    text = text[:start] + func + text[end:]

    insert = text.find(sig)
    text = text[:insert] + enabled_helper("r7p_progress_enabled") + text[insert:]
    write_text(path, text)


def patch_metadata(path):
    text = read_text(path)
    if MARKER in text:
        return
    sig = "static int stream_remote_resourcefork_to_local("
    start, end = function_span(text, sig)
    func = text[start:end]

    old = """        offset += received;\n        if (eof && offset < total) {\n"""
    new = r'''        offset += received;
        if (r7p_metadata_progress_enabled()) {
            printf("R7P: resource path=%s delta=%u total=%llu expected=%llu\n",
                   source_path, received, offset, total);
            fflush(stdout);
        }
        if (eof && offset < total) {
'''
    if func.count(old) != 1:
        die("metadata resource progress guard count={}".format(func.count(old)))
    func = func.replace(old, new, 1)
    text = text[:start] + func + text[end:]

    insert = text.find(sig)
    text = text[:insert] + enabled_helper("r7p_metadata_progress_enabled") + text[insert:]
    write_text(path, text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_progress_telemetry_r7p.py NETATALK_CLIENT_TREE")
    root = os.path.abspath(sys.argv[1])
    cmdline = os.path.join(root, "cmdline", "cmdline_afp.c")
    metadata = os.path.join(root, "daemon", "metadata.c")
    for path in (cmdline, metadata):
        if not os.path.isfile(path):
            die("required source missing: {}".format(path))

    patch_cmdline(cmdline)
    patch_metadata(metadata)

    print("R7P progress telemetry ready: {}".format(root))
    print("  data-fork telemetry: actual successful AFP read bytes")
    print("  resource telemetry: actual successful resource read bytes")
    print("  enabled only by GT_AFP_PROGRESS_TELEMETRY=1")
    print("  AFP/recovery behavior unchanged")


if __name__ == "__main__":
    main()
