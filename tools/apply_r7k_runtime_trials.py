#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7K: runtime trial controls layered on R7J.
#
# Adds two independently selectable experiments without changing the default
# R7J behavior:
#   GT_AFP_R7K_ATP_SENDS=6..12
#       total sends for ordinary R7A ASP command/write transactions.
#       Default 6 keeps R7J/R7A behavior (initial + five retransmissions).
#   GT_AFP_R7K_INTERFILE_MS=0..250
#       recovery-prevention pause after a successfully preserved file's
#       metadata stage. Default 0 keeps R7J behavior.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK FINDER TOLERANCE R7K"


def die(msg):
    raise SystemExit("apply_r7k_runtime_trials: " + msg)


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


def patch_asp(root):
    path = os.path.join(root, "lib", "asp_transport.c")
    text = read_text(path)

    if "GLOBALTALK FINDER ATP RETRY R7A" not in text:
        die("R7A must be applied before R7K")

    if MARKER in text:
        print("R7K ASP controls already applied: {}".format(path))
        return

    old_assign = "    atpb.atp_sreqtries = 6;\n"
    count = text.count(old_assign)
    if count != 2:
        die("expected two R7A six-send sites, found {}".format(count))

    anchor = "static struct afpc_asp *ctx_of(struct afp_server *server)\n"
    if text.count(anchor) != 1:
        die("ctx_of insertion anchor missing/non-unique")

    helper = r'''/* GLOBALTALK FINDER TOLERANCE R7K
 * Runtime trial control.  Default remains the proven R7A value of six total
 * sends.  The environment is inherited by afpsld and read once per process.
 * Only ordinary R7A ASP command/write sites use this helper. */
static int r7k_atp_total_sends(void)
{
    static int cached = -1;
    const char *value;
    char *end = NULL;
    long parsed;

    if (cached >= 0) {
        return cached;
    }

    cached = 6;
    value = getenv("GT_AFP_R7K_ATP_SENDS");
    if (!value || !*value) {
        return cached;
    }

    errno = 0;
    parsed = strtol(value, &end, 10);
    if (errno == 0 && end && *end == '\0'
            && parsed >= 6 && parsed <= 12) {
        cached = (int)parsed;
    }

    return cached;
}

'''
    text = text.replace(anchor, helper + anchor, 1)
    text = text.replace(old_assign,
                        "    atpb.atp_sreqtries = r7k_atp_total_sends();\n")
    write_text(path, text)
    print("Applied R7K runtime ATP-send control: {}".format(path))
    print("  default total sends: 6")
    print("  selectable range: 6..12")
    print("  retry timer remains 2 seconds")


def patch_cmdline(root):
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    text = read_text(path)

    if "GLOBALTALK DEEP RECOVERY R7J" not in text:
        die("R7J must be applied before R7K")

    if MARKER in text:
        print("R7K cmdline controls already applied: {}".format(path))
        return

    signature = "static int copy_remote_metadata_to_local("
    start, end = function_span(text, signature)
    func = text[start:end]

    helper = r'''/* GLOBALTALK FINDER TOLERANCE R7K
 * Optional post-object think time.  This is a trial knob motivated by the
 * classic Finder comparison and by the earlier observation that removing
 * otherwise-redundant AFP work increased stall frequency on the old server.
 * Default zero preserves R7J exactly. */
static unsigned int r7k_interfile_delay_us(void)
{
    static int initialized = 0;
    static unsigned int cached = 0;
    const char *value;
    char *end = NULL;
    long parsed;

    if (initialized) {
        return cached;
    }
    initialized = 1;

    value = getenv("GT_AFP_R7K_INTERFILE_MS");
    if (!value || !*value) {
        return 0;
    }

    errno = 0;
    parsed = strtol(value, &end, 10);
    if (errno == 0 && end && *end == '\0'
            && parsed >= 0 && parsed <= 250) {
        cached = (unsigned int)parsed * 1000U;
    }

    return cached;
}

'''
    text = text[:start] + helper + text[start:]

    # Re-find the function after helper insertion and add the delay only to
    # its successful final exit.  Recovery/error exits remain unchanged.
    start, end = function_span(text, signature)
    func = text[start:end]
    needle = "    return 0;\n}"
    pos = func.rfind(needle)
    if pos < 0:
        die("metadata final-success return guard not found")

    replacement = r'''    {
        unsigned int delay_us = r7k_interfile_delay_us();
        if (delay_us != 0) {
            usleep(delay_us);
        }
    }

    return 0;
}'''
    func = func[:pos] + replacement + func[pos + len(needle):]
    text = text[:start] + func + text[end:]

    write_text(path, text)
    print("Applied R7K runtime inter-file pacing control: {}".format(path))
    print("  default delay: 0 ms")
    print("  selectable range: 0..250 ms")
    print("  delay occurs only after successful metadata preservation")


def main():
    if len(sys.argv) != 2:
        die("usage: apply_r7k_runtime_trials.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    if not os.path.isfile(os.path.join(root, "lib", "asp_transport.c")):
        die("patched Netatalk Client tree not found: {}".format(root))

    patch_asp(root)
    patch_cmdline(root)

    print("R7K Finder-tolerance runtime trials ready")
    print("  GT_AFP_R7K_ATP_SENDS=6..12 (default 6)")
    print("  GT_AFP_R7K_INTERFILE_MS=0..250 (default 0)")
    print("  R7J recovery policy retained")


if __name__ == "__main__":
    main()
