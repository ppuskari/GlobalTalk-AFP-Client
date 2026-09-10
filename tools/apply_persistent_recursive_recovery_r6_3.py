#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R6.3 staged hardening.
#
# Layered after R6.2.  Add bounded recovery at recursive directory boundaries:
# the initial directory stat and a failed whole-directory listing may recover
# once before the traversal aborts.  This is separate from the file and
# metadata recovery layers so it can be tested independently.
#
# ATP/ASP transport is deliberately untouched.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.3"


def die(msg):
    raise SystemExit("apply_persistent_recursive_recovery_r6_3: " + msg)


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


def patch_download_directory(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]

    old_stat = '''    if (afp_sl_stat(&vol_id, server_path, NULL, &dir_stat) != 0) {\n        char display_remote[AFP_MAX_PATH * 4];\n        printf("Could not stat directory %s\\n",\n               display_text(server_path, display_remote, sizeof(display_remote)));\n        return -1;\n    }\n'''

    new_stat = '''    {\n        int dir_stat_ret;\n        int dir_stat_attempt = 0;\n\nretry_directory_stat:\n        dir_stat_ret = afp_sl_stat(&vol_id, server_path, NULL, &dir_stat);\n        if (dir_stat_ret != 0) {\n            char display_remote[AFP_MAX_PATH * 4];\n            printf("R6.3: directory stat failed path=%s ret=%d attempt=%d\\n",\n                   display_text(server_path, display_remote,\n                                sizeof(display_remote)),\n                   dir_stat_ret, dir_stat_attempt + 1);\n\n            if (dir_stat_attempt == 0\n                    && is_recoverable_session_error(dir_stat_ret)) {\n                int recover_ret;\n                recover_ret = recover_session(1, 1);\n                printf("R6.3: directory stat recovery result path=%s ret=%d\\n",\n                       display_text(server_path, display_remote,\n                                    sizeof(display_remote)),\n                       recover_ret);\n                if (recover_ret == 0) {\n                    dir_stat_attempt = 1;\n                    goto retry_directory_stat;\n                }\n            }\n\n            return -1;\n        }\n    }\n'''

    count = func.count(old_stat)
    if count != 1:
        die("directory stat guard: expected once, found {}".format(count))
    func = func.replace(old_stat, new_stat, 1)

    old_list = '''    if (remote_readdir_all(server_path, &filebase, &numfiles) != 0) {\n        char display_remote[AFP_MAX_PATH * 4];\n        printf("Could not read directory %s\\n",\n               display_text(server_path, display_remote, sizeof(display_remote)));\n\n        if (total_bytes) {\n            *total_bytes = 0;\n        }\n\n        return -1;\n    }\n'''

    new_list = '''    {\n        int list_ret;\n        int list_attempt = 0;\n\nretry_directory_list:\n        filebase = NULL;\n        numfiles = 0;\n        list_ret = remote_readdir_all(server_path, &filebase, &numfiles);\n        if (list_ret != 0) {\n            char display_remote[AFP_MAX_PATH * 4];\n            printf("R6.3: directory listing failed path=%s ret=%d attempt=%d\\n",\n                   display_text(server_path, display_remote,\n                                sizeof(display_remote)),\n                   list_ret, list_attempt + 1);\n\n            if (list_attempt == 0\n                    && (is_recoverable_session_error(list_ret)\n                        || list_ret == -EIO)) {\n                int recover_ret;\n                recover_ret = recover_session(1, 1);\n                printf("R6.3: directory listing recovery result path=%s ret=%d\\n",\n                       display_text(server_path, display_remote,\n                                    sizeof(display_remote)),\n                       recover_ret);\n                if (recover_ret == 0) {\n                    list_attempt = 1;\n                    goto retry_directory_list;\n                }\n            }\n\n            if (total_bytes) {\n                *total_bytes = 0;\n            }\n            return -1;\n        }\n    }\n'''

    count = func.count(old_list)
    if count != 1:
        die("directory listing guard: expected once, found {}".format(count))
    func = func.replace(old_list, new_list, 1)

    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_persistent_recursive_recovery_r6_3.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Persistent recursive recovery R6.3 already applied: {}".format(path))
        return
    if "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2" not in text:
        die("R6.2 must be applied first")

    text = patch_download_directory(text)
    write_text(path, text)

    print("Applied persistent recursive recovery R6.3: {}".format(path))
    print("  directory-entry stat gets one bounded recovery")
    print("  failed whole-directory listing gets one bounded recovery")
    print("  generic listing EIO is treated as a session-integrity event once")
    print("  R6.2 metadata recovery retained")
    print("  R6.1 short-EOF recovery and fail-fast propagation retained")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
