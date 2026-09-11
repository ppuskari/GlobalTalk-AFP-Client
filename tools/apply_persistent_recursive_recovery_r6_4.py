#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R6.4 hardening.
#
# Layered after R6.3.  A late-run remote AFP operation can surface as generic
# -EIO even when the underlying session is the real failure.  Treat remote
# file stat/open/read/close EIO as one bounded session-integrity event, while
# leaving local filesystem EIO untouched.  Also extend the R6.3 directory
# stat boundary to recover once on generic -EIO.
#
# ATP/ASP transport is deliberately untouched.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4"
R63_MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.3"


def die(msg):
    raise SystemExit("apply_persistent_recursive_recovery_r6_4: " + msg)


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


def has_r63(text):
    if R63_MARKER in text:
        return True
    return ("R6.3: directory stat failed" in text
            and "R6.3: directory listing failed" in text)


def patch_retrieve(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]

    old = '''    if (attempt == 0\n            && (short_eof || is_recoverable_session_error(op_ret))) {\n        int recover_ret;\n        printf("R6.1: recovery requested path=%s cause=%s ret=%d\\n",\n               path, short_eof ? "premature-eof" : "session-error", op_ret);\n        recover_ret = recover_session(1, 1);\n        printf("R6.1: recovery result path=%s ret=%d\\n", path, recover_ret);\n        if (recover_ret == 0) {\n            attempt = 1;\n            goto retry_file;\n        }\n    }\n'''

    new = '''    /* GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4 */\n    if (attempt == 0\n            && (short_eof || is_recoverable_session_error(op_ret)\n                || op_ret == -EIO)) {\n        int recover_ret;\n        const char *recover_cause =\n            short_eof ? "premature-eof"\n            : (op_ret == -EIO ? "remote-eio" : "session-error");\n        printf("R6.4: recovery requested path=%s cause=%s ret=%d\\n",\n               path, recover_cause, op_ret);\n        recover_ret = recover_session(1, 1);\n        printf("R6.4: recovery result path=%s ret=%d\\n", path, recover_ret);\n        if (recover_ret == 0) {\n            attempt = 1;\n            goto retry_file;\n        }\n    }\n'''

    count = func.count(old)
    if count != 1:
        die("retrieve remote-EIO recovery guard: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_directory_stat(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]

    old = '''            if (dir_stat_attempt == 0\n                    && is_recoverable_session_error(dir_stat_ret)) {\n                int recover_ret;\n                recover_ret = recover_session(1, 1);\n                printf("R6.3: directory stat recovery result path=%s ret=%d\\n",\n                       display_text(server_path, display_remote,\n                                    sizeof(display_remote)),\n                       recover_ret);\n                if (recover_ret == 0) {\n                    dir_stat_attempt = 1;\n                    goto retry_directory_stat;\n                }\n            }\n'''

    new = '''            if (dir_stat_attempt == 0\n                    && (is_recoverable_session_error(dir_stat_ret)\n                        || dir_stat_ret == -EIO)) {\n                int recover_ret;\n                printf("R6.4: directory stat recovery requested path=%s ret=%d\\n",\n                       display_text(server_path, display_remote,\n                                    sizeof(display_remote)),\n                       dir_stat_ret);\n                recover_ret = recover_session(1, 1);\n                printf("R6.4: directory stat recovery result path=%s ret=%d\\n",\n                       display_text(server_path, display_remote,\n                                    sizeof(display_remote)),\n                       recover_ret);\n                if (recover_ret == 0) {\n                    dir_stat_attempt = 1;\n                    goto retry_directory_stat;\n                }\n            }\n'''

    count = func.count(old)
    if count != 1:
        die("directory stat EIO guard: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_persistent_recursive_recovery_r6_4.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Persistent recursive recovery R6.4 already applied: {}".format(path))
        return
    if not has_r63(text):
        die("R6.3 must be applied first")

    text = patch_retrieve(text)
    text = patch_directory_stat(text)
    write_text(path, text)

    print("Applied persistent recursive recovery R6.4: {}".format(path))
    print("  remote file stat/open/read/close EIO gets one bounded recovery")
    print("  directory stat EIO gets one bounded recovery")
    print("  local filesystem errors do not trigger AFP reconnect")
    print("  R6.3 directory-list recovery retained")
    print("  R6.2 metadata recovery retained")
    print("  R6.1 short-EOF recovery and fail-fast propagation retained")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
