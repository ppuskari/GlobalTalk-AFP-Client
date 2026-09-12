#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7I: resumable data-fork recovery.
#
# Layered on the proven R7E tree.  Preserve successfully written bytes across
# AFP session recovery, validate the remote object before continuing, then
# reopen the fork and resume from the last verified offset.
#
# Normal no-error traffic is unchanged.  ATP/ASP transport, retry timing,
# enumeration, metadata, resource forks, DID caching, and zero-fork behavior
# are unchanged.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RESUME DATAFORK R7I"
R7E_MARKER = "GLOBALTALK ZERO DATAFORK SKIP R7E"
R7D_MARKER = "GLOBALTALK FINDER RECOVERY DID R7D"


def die(msg):
    raise SystemExit("apply_resume_datafork_r7i: " + msg)


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
    struct stat expected_stat;
    int ret = -1;
    int op_ret = 0;
    int short_eof = 0;
    int recoveries = 0;
    const int max_recoveries = 3;

    *amount_written = 0;

    if (!vol_id) {
        printf("You're not attached to a volume\n");
        goto out;
    }

    if (get_server_path(arg, path)) {
        printf("Invalid path\n");
        goto out;
    }

    /* GLOBALTALK RESUME DATAFORK R7I */
    if (!stat) {
        op_ret = -EINVAL;
        printf("R7I: missing caller metadata path=%s ret=%d\n", path, op_ret);
        goto out;
    }
    expected_stat = *stat;

    if (verbose_mode) {
        printf("R7B: reusing caller/enumeration metadata path=%s size=%llu\n",
               path, (unsigned long long)expected_stat.st_size);
    }

    gettimeofday(&starttv, NULL);

retry_file:
    fileid = 0;
    file_opened = 0;
    eof = 0;
    received = 0;
    short_eof = 0;
    offset = total;

    if (recoveries > 0) {
        printf("R7I: resuming current file path=%s offset=%llu recovery=%d/%d\n",
               path, offset, recoveries, max_recoveries);
    }

    /* A recovered close failure can occur after every expected byte has been
     * committed locally.  The reconnect invalidated the old fork ref, so there
     * is nothing left to read; proceed directly to final size validation. */
    if ((unsigned long long)expected_stat.st_size == total) {
        goto complete_file;
    }

    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
    if (op_ret != 0) {
        printf("R6.1: open failed path=%s ret=%d\n", path, op_ret);
        if (op_ret == -ENOENT) {
            printf("R7B: enumerated object could not be reopened by full path: %s\n",
                   path);
        }
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

    if (expected_stat.st_size >= 0
            && total != (unsigned long long)expected_stat.st_size) {
        short_eof = 1;
        printf("R6.1: premature EOF path=%s expected=%llu received=%llu offset=%llu eof=%u\n",
               path, (unsigned long long)expected_stat.st_size,
               total, offset, eof);
        op_ret = -EIO;
        goto recover_or_out;
    }

complete_file:
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

    if (recoveries < max_recoveries
            && (short_eof || is_recoverable_session_error(op_ret)
                || op_ret == -EIO)) {
        int recover_ret;
        int prime_ret;
        struct stat fresh_stat;
        const char *recover_cause =
            short_eof ? "premature-eof"
            : (op_ret == -EIO ? "remote-eio" : "session-error");

        printf("R7I: recovery requested path=%s cause=%s ret=%d offset=%llu recovery=%d/%d\n",
               path, recover_cause, op_ret, total,
               recoveries + 1, max_recoveries);

        recover_ret = recover_session(1, 1);
        printf("R7I: recovery result path=%s ret=%d\n", path, recover_ret);
        if (recover_ret != 0) {
            goto unrecovered;
        }

        prime_ret = r7d_prime_parent_did_chain(path);
        printf("R7I: recovery DID-prime path=%s ret=%d\n", path, prime_ret);
        if (prime_ret != 0) {
            op_ret = prime_ret;
            goto unrecovered;
        }

        memset(&fresh_stat, 0, sizeof(fresh_stat));
        op_ret = afp_sl_stat(&vol_id, path, NULL, &fresh_stat);
        if (op_ret != 0) {
            printf("R7I: resume validation stat failed path=%s ret=%d\n",
                   path, op_ret);
            goto unrecovered;
        }

        if (fresh_stat.st_size != expected_stat.st_size
                || fresh_stat.st_mtime != expected_stat.st_mtime) {
            printf("R7I: resume validation mismatch path=%s "
                   "expected-size=%llu fresh-size=%llu "
                   "expected-mtime=%lld fresh-mtime=%lld\n",
                   path,
                   (unsigned long long)expected_stat.st_size,
                   (unsigned long long)fresh_stat.st_size,
                   (long long)expected_stat.st_mtime,
                   (long long)fresh_stat.st_mtime);
            op_ret = -ESTALE;
            goto unrecovered;
        }

        if (ftruncate(fd, (off_t)total) != 0
                || lseek(fd, (off_t)total, SEEK_SET) < 0) {
            printf("R7I: could not position local partial file path=%s offset=%llu\n",
                   path, total);
            ret = -1;
            goto out;
        }

        recoveries++;
        printf("R7I: resume validation passed path=%s offset=%llu size=%llu mtime=%lld\n",
               path, total,
               (unsigned long long)expected_stat.st_size,
               (long long)expected_stat.st_mtime);
        goto retry_file;
    }

unrecovered:
    printf("R7I: unrecovered file failure path=%s ret=%d bytes=%llu recoveries=%d\n",
           path, op_ret, total, recoveries);
    ret = -1;
out:
    *amount_written = total;
    if (file_opened && fileid) {
        int close_ret = afp_sl_close(&vol_id, fileid);
        if (close_ret != 0) {
            printf("R7I: final remote close failed path=%s ret=%d\n",
                   path, close_ret);
            if (ret == 0) {
                ret = -1;
            }
        }
    }
    return ret;
}'''

    return text[:start] + replacement + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_resume_datafork_r7i.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")

    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Resume data-fork R7I already applied: {}".format(path))
        return
    if R7E_MARKER not in text:
        die("R7E must be applied first")
    if R7D_MARKER not in text:
        die("R7D must be applied first")

    text = patch_retrieve(text)
    write_text(path, text)

    print("Applied resumable data-fork recovery R7I: {}".format(path))
    print("  successfully written bytes survive reconnect")
    print("  recovered session rebuilds parent DID chain")
    print("  fresh stat must match original size and modification time")
    print("  local file is truncated/positioned to last verified byte")
    print("  recovered fork resumes at that exact AFP read offset")
    print("  up to 3 in-process recoveries are allowed per file")
    print("  normal no-error data path and ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
