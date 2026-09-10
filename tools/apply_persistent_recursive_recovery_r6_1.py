#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R6.1 hardening.
#
# Layered after R6.  Treat a short EOF as probable session loss for one
# recovery attempt, add precise transfer diagnostics, and stop recursive
# traversal when a child directory fails instead of advancing to siblings.
# ATP/ASP transport is deliberately untouched.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1"


def die(msg):
    raise SystemExit("apply_persistent_recursive_recovery_r6_1: " + msg)


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


def replace_function(text, signature, replacement):
    start, end = function_span(text, signature)
    return text[:start] + replacement + text[end:]


def patch_retrieve(text):
    replacement = r'''static int retrieve_file(char * arg, int fd, struct stat *stat,
                         unsigned long long *amount_written)
{
    unsigned int fileid = 0;
    int file_opened = 0;
    char path[PATH_MAX];
    unsigned long long offset = 0;
#define BUF_SIZE 102400
    unsigned int size = BUF_SIZE;
    char buf[BUF_SIZE];
    unsigned int received = 0, eof = 0;
    unsigned long long total = 0;
    struct timeval starttv, endtv;
    int ret = -1;
    int attempt = 0;
    int op_ret = 0;
    int short_eof = 0;

    *amount_written = 0;

    if (!vol_id) {
        printf("You're not attached to a volume\n");
        goto out;
    }

    if (get_server_path(arg, path)) {
        printf("Invalid path\n");
        goto out;
    }

    gettimeofday(&starttv, NULL);

    /* GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1 */
retry_file:
    fileid = 0;
    file_opened = 0;
    offset = 0;
    eof = 0;
    total = 0;
    received = 0;
    short_eof = 0;

    if (attempt > 0) {
        if (ftruncate(fd, 0) != 0 || lseek(fd, 0, SEEK_SET) < 0) {
            printf("R6.1: could not reset local file for retry: %s\n", path);
            ret = -1;
            goto out;
        }
        printf("R6.1: retrying current file from offset zero: %s\n", path);
    }

    op_ret = afp_sl_stat(&vol_id, path, NULL, stat);
    if (op_ret != 0) {
        printf("R6.1: stat failed path=%s ret=%d\n", path, op_ret);
        goto recover_or_out;
    }

    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
    if (op_ret != 0) {
        printf("R6.1: open failed path=%s ret=%d\n", path, op_ret);
        goto recover_or_out;
    }
    file_opened = 1;

    while (!eof) {
        memset(buf, 0, BUF_SIZE);
        received = 0;
        op_ret = afp_sl_read(&vol_id, fileid, 0, offset, size,
                             &received, &eof, buf);

        if (op_ret != 0) {
            printf("R6.1: read failed path=%s ret=%d offset=%llu request=%u received=%u eof=%u\n",
                   path, op_ret, offset, size, received, eof);
            goto recover_or_out;
        }

        if (received == 0) {
            printf("R6.1: zero-byte read path=%s offset=%llu request=%u eof=%u\n",
                   path, offset, size, eof);
            break;
        }

        if (write_all_fd(fd, buf, received) < 0) {
            printf("R6.1: local write failed path=%s offset=%llu bytes=%u\n",
                   path, offset, received);
            ret = -1;
            goto out;
        }

        total += received;
        offset += received;
    }

    if (stat && stat->st_size >= 0
            && total != (unsigned long long)stat->st_size) {
        short_eof = 1;
        printf("R6.1: premature EOF path=%s expected=%llu received=%llu offset=%llu eof=%u\n",
               path, (unsigned long long)stat->st_size, total, offset, eof);
        op_ret = -EIO;
        goto recover_or_out;
    }

    if (file_opened && fileid) {
        op_ret = afp_sl_close(&vol_id, fileid);
        file_opened = 0;
        fileid = 0;
        if (op_ret != 0) {
            printf("R6.1: remote close failed path=%s ret=%d\n", path, op_ret);
            goto recover_or_out;
        }
    }

    if (verbose_mode) {
        gettimeofday(&endtv, NULL);
        printdiff(&starttv, &endtv, &total);
    }

    *amount_written = total;
    ret = 0;
    goto out;

recover_or_out:
    if (file_opened && fileid) {
        int close_ret = afp_sl_close(&vol_id, fileid);
        printf("R6.1: best-effort close path=%s ret=%d\n", path, close_ret);
        file_opened = 0;
        fileid = 0;
    }

    if (attempt == 0
            && (short_eof || is_recoverable_session_error(op_ret))) {
        int recover_ret;
        printf("R6.1: recovery requested path=%s cause=%s ret=%d\n",
               path, short_eof ? "premature-eof" : "session-error", op_ret);
        recover_ret = recover_session(1, 1);
        printf("R6.1: recovery result path=%s ret=%d\n", path, recover_ret);
        if (recover_ret == 0) {
            attempt = 1;
            goto retry_file;
        }
    }

    printf("R6.1: unrecovered file failure path=%s ret=%d bytes=%llu\n",
           path, op_ret, total);
    ret = -1;
out:
    *amount_written = total;
    if (file_opened && fileid) {
        int close_ret = afp_sl_close(&vol_id, fileid);
        if (close_ret != 0) {
            printf("R6.1: final remote close failed path=%s ret=%d\n",
                   path, close_ret);
            if (ret == 0) {
                ret = -1;
            }
        }
    }
    return ret;
}'''
    return replace_function(text, "static int retrieve_file(", replacement)


def patch_recursive_propagation(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]
    old = '''            if (download_directory(new_server_path, new_local_path, &subdir_bytes) < 0) {\n                ret = -1;\n            } else {\n                bytes += subdir_bytes;\n            }\n'''
    new = '''            if (download_directory(new_server_path, new_local_path, &subdir_bytes) < 0) {\n                char display_remote[AFP_MAX_PATH * 4];\n                printf("R6.1: child directory failed; stopping parent traversal: %s\\n",\n                       display_text(new_server_path, display_remote,\n                                    sizeof(display_remote)));\n                ret = -1;\n                break;\n            } else {\n                bytes += subdir_bytes;\n            }\n'''
    count = func.count(old)
    if count != 1:
        die("recursive child propagation guard: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_persistent_recursive_recovery_r6_1.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Persistent recursive recovery R6.1 already applied: {}".format(path))
        return
    if "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6" not in text:
        die("R6 must be applied first")

    text = patch_retrieve(text)
    text = patch_recursive_propagation(text)
    write_text(path, text)

    print("Applied persistent recursive recovery R6.1: {}".format(path))
    print("  premature EOF gets one in-process session recovery")
    print("  retry restarts the current file from offset zero")
    print("  read/EOF/close/recovery diagnostics enabled")
    print("  unrecovered child directory failure stops parent traversal")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
