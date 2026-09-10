#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R6: persistent recursive session recovery.
#
# Keep one AFP login/volume attachment for a recursive pull, like a classic
# Finder copy.  Recover only when an operation reports a recoverable session
# failure.  The current file is then retried from offset zero in the recovered
# session.  ATP/ASP transport is not changed here.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6"


def die(msg):
    raise SystemExit("apply_persistent_recursive_recovery_r6: " + msg)


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


def patch_remote_readdir_all(text):
    replacement = r'''static int remote_readdir_all(const char *path,
                              struct afp_file_info_basic **files,
                              unsigned int *count)
{
    struct afp_file_info_basic *all = NULL;
    size_t total = 0;
    int eod = 0;

    /* GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6 */
    while (!eod) {
        struct afp_file_info_basic *page = NULL;
        unsigned int page_count = 0;
        int retried = 0;
        int ret;

        if (total > INT_MAX) {
            free(all);
            return -EOVERFLOW;
        }

retry_page:
        ret = afp_sl_readdir(&vol_id, path, NULL, (int)total, 256,
                             &page_count, &page, &eod);

        if (ret != 0 && !retried && is_recoverable_session_error(ret)) {
            free(page);
            page = NULL;
            page_count = 0;
            eod = 0;
            if (recover_session(1, 1) == 0) {
                retried = 1;
                printf("R6: recovered AFP session while listing %s; retrying page at entry %lu\n",
                       path, (unsigned long)total);
                goto retry_page;
            }
        }

        if (ret != 0) {
            free(page);
            free(all);
            return ret;
        }

        if (page_count == 0) {
            free(page);
            break;
        }

        if ((size_t)page_count > SIZE_MAX / sizeof(*all) - total) {
            free(page);
            free(all);
            return -EOVERFLOW;
        }

        {
            size_t new_total = total + (size_t)page_count;
            struct afp_file_info_basic *grown = realloc(
                all, new_total * sizeof(*all));

            if (!grown) {
                free(page);
                free(all);
                return -ENOMEM;
            }

            all = grown;
            memcpy(all + total, page,
                   (size_t)page_count * sizeof(*all));
            total = new_total;
        }
        free(page);
    }

    if (total > UINT_MAX) {
        free(all);
        return -EOVERFLOW;
    }

    *files = all;
    *count = (unsigned int)total;
    return 0;
}'''
    return replace_function(text, "static int remote_readdir_all(", replacement)


def patch_metadata(text):
    replacement = r'''static int copy_remote_metadata_to_local(const char *remote_path,
        const char *local_path, const struct stat *st)
{
    unsigned int warnings = 0;
    int ret;
    int retried = 0;

    if (transfer_metadata_mode == AFP_METADATA_NONE) {
        return 0;
    }

retry_metadata:
    warnings = 0;
    ret = afp_sl_metadata_copy_remote_to_local(&vol_id, remote_path,
          local_path, transfer_metadata_mode, &warnings);
    metadata_warn(warnings);

    if (ret < 0 && !retried && is_recoverable_session_error(ret)) {
        if (recover_session(1, 1) == 0) {
            retried = 1;
            printf("R6: recovered AFP session while preserving metadata for %s; retrying\n",
                   remote_path);
            goto retry_metadata;
        }
    }

    if (ret < 0) {
        return ret;
    }

    if (chmod(local_path, st->st_mode & 07777) < 0 && errno != EPERM) {
        return -errno;
    }

    {
        struct timespec times[2] = {
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
        };
        return utimensat(AT_FDCWD, local_path, times, 0) < 0 ? -errno : 0;
    }
}'''
    return replace_function(text, "static int copy_remote_metadata_to_local(", replacement)


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
    unsigned int received, eof = 0;
    unsigned long long total = 0;
    struct timeval starttv, endtv;
    int ret = -1;
    int attempt = 0;
    int op_ret = 0;

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

    /* GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6
     * Keep the caller's AFP connection for normal progress.  Only a
     * recoverable session error reconnects.  A recovered file restarts at
     * offset zero so data-fork integrity is deterministic. */
retry_file:
    fileid = 0;
    file_opened = 0;
    offset = 0;
    eof = 0;
    total = 0;
    received = 0;

    if (attempt > 0) {
        if (ftruncate(fd, 0) != 0 || lseek(fd, 0, SEEK_SET) < 0) {
            printf("Could not reset local file for AFP retry\n");
            ret = -1;
            goto out;
        }
        printf("R6: retrying current file from offset zero: %s\n", path);
    }

    op_ret = afp_sl_stat(&vol_id, path, NULL, stat);
    if (op_ret != 0) {
        printf("Could not get file attributes for file %s\n", path);
        goto recover_or_out;
    }

    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
    if (op_ret != 0) {
        printf("Could not open %s on server\n", arg);
        goto recover_or_out;
    }
    file_opened = 1;

    while (!eof) {
        memset(buf, 0, BUF_SIZE);
        op_ret = afp_sl_read(&vol_id, fileid, 0, offset, size,
                             &received, &eof, buf);

        if (op_ret != 0) {
            printf("Error reading file %s\n", path);
            goto recover_or_out;
        }

        if (received == 0) {
            break;
        }

        if (write_all_fd(fd, buf, received) < 0) {
            printf("Error writing local file\n");
            ret = -1;
            goto out;
        }

        total += received;
        offset += received;
    }

    if (stat && stat->st_size >= 0
            && total != (unsigned long long)stat->st_size) {
        printf("Incomplete remote file: expected %llu bytes, received %llu bytes\n",
               (unsigned long long)stat->st_size, total);
        op_ret = -EIO;
        goto recover_or_out;
    }

    if (file_opened && fileid) {
        op_ret = afp_sl_close(&vol_id, fileid);
        file_opened = 0;
        fileid = 0;
        if (op_ret != 0) {
            printf("Could not close remote file (result=%d)\n", op_ret);
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
        /* Best effort only.  A broken session may reject this close. */
        afp_sl_close(&vol_id, fileid);
        file_opened = 0;
        fileid = 0;
    }

    if (attempt == 0 && is_recoverable_session_error(op_ret)
            && recover_session(1, 1) == 0) {
        attempt = 1;
        printf("R6: recovered AFP session during file transfer: %s\n", path);
        goto retry_file;
    }

    ret = -1;
out:
    *amount_written = total;
    if (file_opened && fileid) {
        int close_ret = afp_sl_close(&vol_id, fileid);
        if (close_ret != 0 && ret == 0) {
            ret = -1;
        }
    }
    return ret;
}'''
    return replace_function(text, "static int retrieve_file(", replacement)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_persistent_recursive_recovery_r6.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Persistent recursive recovery R6 already applied: {}".format(path))
        return
    if "GLOBALTALK BATCH INTEGRITY R2" not in text:
        die("batch integrity R2 must be applied first")

    text = patch_remote_readdir_all(text)
    text = patch_metadata(text)
    text = patch_retrieve(text)
    write_text(path, text)

    print("Applied persistent recursive recovery R6: {}".format(path))
    print("  one AFP login/volume attachment per recursive pull")
    print("  directory page retry after recoverable session failure")
    print("  current file retries from offset zero after recovery")
    print("  metadata retries after recoverable session failure")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
