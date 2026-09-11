#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Harden Netatalk Client 0.9.5 batch transfers for archive use.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import subprocess
import sys

MARKER = "GLOBALTALK BATCH INTEGRITY R2"


def die(msg):
    raise SystemExit("apply_batch_integrity_r2: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


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

    old_success = '''    if (verbose_mode) {\n        gettimeofday(&endtv, NULL);\n        printdiff(&starttv, &endtv, &total);\n    }\n\n    *amount_written = total;\n    ret = 0;\nout:\n\n    /* Do not close fd here, caller owns it */\n    if (file_opened && fileid) {\n        afp_sl_close(&vol_id, fileid);\n    }\n\n    return ret;\n'''

    new_success = '''    if (verbose_mode) {\n        gettimeofday(&endtv, NULL);\n        printdiff(&starttv, &endtv, &total);\n    }\n\n    /* GLOBALTALK BATCH INTEGRITY R2 */\n    if (stat && stat->st_size >= 0\n            && total != (unsigned long long)stat->st_size) {\n        printf("Incomplete remote file: expected %llu bytes, received %llu bytes\\n",\n               (unsigned long long)stat->st_size, total);\n        ret = -1;\n        goto out;\n    }\n\n    ret = 0;\nout:\n\n    *amount_written = total;\n\n    if (file_opened && fileid) {\n        int close_ret = afp_sl_close(&vol_id, fileid);\n        if (close_ret != 0) {\n            printf("Could not close remote file (result=%d)\\n", close_ret);\n            if (ret == 0) {\n                ret = -1;\n            }\n        }\n    }\n\n    return ret;\n'''

    func = replace_once(func, old_success, new_success, "retrieve_file integrity")
    return text[:start] + func + text[end:]


def patch_download_directory(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]

    old_file = '''            if (retrieve_file(new_server_path, fd, &st, &amount) < 0) {\n                ret = -1;\n            } else {\n                bytes += amount;\n            }\n\n            close(fd);\n\n            if (copy_remote_metadata_to_local(new_server_path, new_local_path,\n                                              &st) < 0) {\n                char display_remote[AFP_MAX_PATH * 4];\n                printf("Could not preserve metadata for %s\\n",\n                       display_text(new_server_path, display_remote,\n                                    sizeof(display_remote)));\n                ret = -1;\n            }\n'''

    new_file = '''            {\n                int file_ret = retrieve_file(new_server_path, fd, &st, &amount);\n                close(fd);\n\n                if (file_ret < 0) {\n                    ret = -1;\n                    break;\n                }\n\n                bytes += amount;\n            }\n\n            if (copy_remote_metadata_to_local(new_server_path, new_local_path,\n                                              &st) < 0) {\n                char display_remote[AFP_MAX_PATH * 4];\n                printf("Could not preserve metadata for %s\\n",\n                       display_text(new_server_path, display_remote,\n                                    sizeof(display_remote)));\n                ret = -1;\n                break;\n            }\n'''

    func = replace_once(func, old_file, new_file,
                        "download_directory file failure")

    old_dir_meta = '''    if (copy_remote_metadata_to_local(server_path, local_path, &dir_stat) < 0) {\n        char display_remote[AFP_MAX_PATH * 4];\n        printf("Could not preserve directory metadata for %s\\n",\n               display_text(server_path, display_remote, sizeof(display_remote)));\n        ret = -1;\n    }\n'''

    new_dir_meta = '''    if (ret == 0\n            && copy_remote_metadata_to_local(server_path, local_path, &dir_stat) < 0) {\n        char display_remote[AFP_MAX_PATH * 4];\n        printf("Could not preserve directory metadata for %s\\n",\n               display_text(server_path, display_remote, sizeof(display_remote)));\n        ret = -1;\n    }\n'''

    func = replace_once(func, old_dir_meta, new_dir_meta,
                        "download_directory final metadata")
    return text[:start] + func + text[end:]


def patch_batch_report(text):
    start, end = function_span(text, "int cmdline_batch_transfer(")
    func = text[start:end]

    old = '''    if (bytes_transferred > 0) {\n        if (direction == 0) {\n            printf("Transfer complete. %llu bytes received.\\n", bytes_transferred);\n        } else {\n            printf("Transfer complete. %llu bytes sent.\\n", bytes_transferred);\n        }\n    }\n'''

    new = '''    /* GLOBALTALK BATCH INTEGRITY R2 */\n    if (ret == 0 && bytes_transferred > 0) {\n        if (direction == 0) {\n            printf("Transfer complete. %llu bytes received.\\n", bytes_transferred);\n        } else {\n            printf("Transfer complete. %llu bytes sent.\\n", bytes_transferred);\n        }\n    } else if (ret != 0 && bytes_transferred > 0) {\n        if (direction == 0) {\n            printf("Transfer failed after %llu bytes received.\\n", bytes_transferred);\n        } else {\n            printf("Transfer failed after %llu bytes sent.\\n", bytes_transferred);\n        }\n    }\n'''

    func = replace_once(func, old, new, "batch completion report")
    return text[:start] + func + text[end:]


def run_recovery_layer(root, name):
    patcher = os.path.join(os.path.dirname(__file__), name)
    subprocess.check_call([sys.executable, patcher, root])


def main():
    if len(sys.argv) != 2:
        die("usage: apply_batch_integrity_r2.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")

    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)

    if MARKER not in text:
        text = patch_retrieve(text)
        text = patch_download_directory(text)
        text = patch_batch_report(text)
        write_text(path, text)
        print("Applied batch integrity R2: {}".format(path))
        print("  exact data-fork size required")
        print("  remote close failures propagated")
        print("  recursive download fails fast")
        print("  partial transfers never report complete")
    else:
        print("Batch integrity R2 already applied: {}".format(path))

    enable_r7b = os.environ.get("GT_AFP_ENABLE_R7B") == "1"
    enable_r7a = (os.environ.get("GT_AFP_ENABLE_R7A") == "1"
                  or enable_r7b)
    enable_r6_4 = (os.environ.get("GT_AFP_ENABLE_R6_4") == "1"
                   or enable_r7a)
    enable_r6_3 = (os.environ.get("GT_AFP_ENABLE_R6_3") == "1"
                   or enable_r6_4)
    enable_r6_2 = (os.environ.get("GT_AFP_ENABLE_R6_2") == "1"
                   or enable_r6_3)
    enable_r6_1 = (os.environ.get("GT_AFP_ENABLE_R6_1") == "1"
                   or enable_r6_2)
    enable_r6 = (os.environ.get("GT_AFP_ENABLE_R6") == "1"
                 or enable_r6_1)

    if enable_r6:
        run_recovery_layer(root, "apply_persistent_recursive_recovery_r6.py")
    if enable_r6_1:
        run_recovery_layer(root, "apply_persistent_recursive_recovery_r6_1.py")
    if enable_r6_2:
        run_recovery_layer(root, "apply_persistent_recursive_recovery_r6_2.py")
    if enable_r6_3:
        run_recovery_layer(root, "apply_persistent_recursive_recovery_r6_3.py")
    if enable_r6_4:
        run_recovery_layer(root, "apply_persistent_recursive_recovery_r6_4.py")
    if enable_r7a:
        run_recovery_layer(root, "apply_finder_atp_retry_r7a.py")
    if enable_r7b:
        run_recovery_layer(root, "apply_finder_enum_metadata_r7b.py")


if __name__ == "__main__":
    main()
