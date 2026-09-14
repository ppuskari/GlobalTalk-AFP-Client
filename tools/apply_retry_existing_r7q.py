#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7Q: retry-safe handling of existing local files.
#
# A rerun after Ctrl-C or a remote-session failure should not blindly
# redownload every file that completed successfully before the failure.
# Treat an existing regular local data fork as reusable only when its exact
# size and preserved modification time match the remote metadata already
# available to the caller.  Matching data is skipped, but metadata/resource
# preservation is still executed.  Any mismatch is overwritten from byte 0.
#
# This deliberately does NOT resume an arbitrary pre-existing partial file.
# Cross-process partial resume would need persistent remote object identity;
# R7I.2 CNID validation is authoritative only inside the active transfer.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RETRY EXISTING R7Q"


def die(msg):
    raise SystemExit("apply_retry_existing_r7q: " + msg)


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


def block_span(text, open_brace):
    depth = 0
    i = open_brace
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
                    return open_brace, i + 1
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
    die("unterminated block")


def insert_helper(text):
    signature = "static int download_directory("
    pos = text.find(signature)
    if pos < 0:
        die("download_directory not found")
    helper = r'''/* GLOBALTALK RETRY EXISTING R7Q
 * Return whether a previously downloaded local data fork can be reused.
 * Exact size + preserved AFP modification time is the conservative
 * no-extra-network equivalence test.  Metadata/resource data is refreshed
 * even when the data fork is reused. */
static int r7q_existing_local(const char *path, const struct stat *remote,
                              struct stat *local, int *exists, int *match)
{
    if (!path || !remote || !local || !exists || !match) {
        return -EINVAL;
    }

    memset(local, 0, sizeof(*local));
    *exists = 0;
    *match = 0;

    if (lstat(path, local) < 0) {
        if (errno == ENOENT) {
            return 0;
        }
        return -errno;
    }

    *exists = 1;
    if (!S_ISREG(local->st_mode)) {
        return -EEXIST;
    }

    if (local->st_size == remote->st_size
            && local->st_mtime == remote->st_mtime) {
        *match = 1;
    }

    return 0;
}

'''
    return text[:pos] + helper + text[pos:]


def patch_recursive(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]
    needle = "            int fd = open(new_local_path, O_CREAT | O_TRUNC | O_RDWR, 0644);"
    fdpos = func.find(needle)
    if fdpos < 0:
        die("recursive local-file open guard not found")

    elsepos = func.rfind("        } else {", 0, fdpos)
    if elsepos < 0:
        die("recursive file else block not found")
    brace = func.find("{", elsepos)
    bstart, bend = block_span(func, brace)
    if bstart != brace:
        die("recursive block parser mismatch")

    replacement = r'''        } else {
            struct stat local_st;
            unsigned long long amount = 0;
            int local_exists = 0;
            int local_match = 0;
            int local_ret;
            int fd = -1;

            /* Construct the authoritative remote stat from the immediately
             * preceding enumeration result, including the R7I.2 CNID. */
            memset(&st, 0, sizeof(st));
            st.st_mode = p->unixprivs.permissions;
            st.st_size = p->size;
            /* GLOBALTALK RESUME IDENTITY R7I.2 */
            st.st_ino = p->fileid;
            st.st_uid = p->unixprivs.uid;
            st.st_gid = p->unixprivs.gid;
            st.st_mtime = p->modification_date;

            local_ret = r7q_existing_local(new_local_path, &st, &local_st,
                                           &local_exists, &local_match);
            if (local_ret < 0) {
                char display_local[PATH_MAX * 4];
                printf("R7Q: existing-local check failed local=%s ret=%d\n",
                       display_text(new_local_path, display_local,
                                    sizeof(display_local)), local_ret);
                ret = -1;
                break;
            }

            if (verbose_mode) {
                char display_name[AFP_MAX_PATH * 4];
                printf("    Downloading file %s\n",
                       display_text(p->name, display_name, sizeof(display_name)));
            }

            if (local_match) {
                printf("R7Q: skip-data size=%llu path=%s\n",
                       (unsigned long long)st.st_size, new_server_path);
            } else {
                if (local_exists) {
                    printf("R7Q: overwrite-local path=%s local-size=%llu "
                           "remote-size=%llu local-mtime=%lld remote-mtime=%lld\n",
                           new_server_path,
                           (unsigned long long)local_st.st_size,
                           (unsigned long long)st.st_size,
                           (long long)local_st.st_mtime,
                           (long long)st.st_mtime);
                }

                fd = open(new_local_path, O_CREAT | O_TRUNC | O_RDWR, 0644);
                if (fd < 0) {
                    perror("open");
                    ret = -1;
                    break;
                }

                {
                    int file_ret = retrieve_file(new_server_path, fd, &st, &amount);
                    close(fd);
                    fd = -1;

                    if (file_ret < 0) {
                        ret = -1;
                        break;
                    }

                    bytes += amount;
                }
            }

            /* Even when data is reused, refresh FinderInfo/resource fork and
             * restore mode/timestamp.  A previous run may have failed exactly
             * in this stage. */
            if (copy_remote_metadata_to_local(new_server_path, new_local_path,
                                              &st) < 0) {
                char display_remote[AFP_MAX_PATH * 4];
                printf("Could not preserve metadata for %s\n",
                       display_text(new_server_path, display_remote,
                                    sizeof(display_remote)));
                ret = -1;
                break;
            }
        }'''

    func = func[:elsepos] + replacement + func[bend:]
    return text[:start] + func + text[end:]


def patch_direct_batch(text):
    start, end = function_span(text, "int cmdline_batch_transfer(")
    func = text[start:end]
    needle = "            int fd = open(dest_path, O_CREAT | O_TRUNC | O_RDWR, 0644);"
    pos = func.find(needle)
    if pos < 0:
        die("direct batch local-file open guard not found")

    finish = func.find("            goto out;", pos)
    if finish < 0:
        die("direct batch file-branch end not found")
    finish += len("            goto out;")

    replacement = r'''            {
                struct stat local_st;
                int local_exists = 0;
                int local_match = 0;
                int local_ret = r7q_existing_local(dest_path, &st, &local_st,
                                                   &local_exists, &local_match);

                if (local_ret < 0) {
                    printf("R7Q: existing-local check failed local=%s ret=%d\n",
                           dest_path, local_ret);
                    goto error;
                }

                if (local_match) {
                    printf("R7Q: skip-data size=%llu path=%s\n",
                           (unsigned long long)st.st_size, remote_path);
                    bytes_transferred = 0;
                    ret = 0;
                } else {
                    int fd;
                    if (local_exists) {
                        printf("R7Q: overwrite-local path=%s local-size=%llu "
                               "remote-size=%llu local-mtime=%lld remote-mtime=%lld\n",
                               remote_path,
                               (unsigned long long)local_st.st_size,
                               (unsigned long long)st.st_size,
                               (long long)local_st.st_mtime,
                               (long long)st.st_mtime);
                    }

                    fd = open(dest_path, O_CREAT | O_TRUNC | O_RDWR, 0644);
                    if (fd < 0) {
                        perror("open");
                        goto error;
                    }

                    ret = retrieve_file(remote_path, fd, &st, &bytes_transferred);
                    close(fd);
                }

                if (ret == 0
                        && copy_remote_metadata_to_local(remote_path, dest_path, &st) < 0) {
                    printf("Could not preserve metadata for %s\n", remote_path);
                    ret = -1;
                }
            }

            goto out;'''

    func = func[:pos] + replacement + func[finish:]
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_retry_existing_r7q.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Retry-existing R7Q already applied: {}".format(path))
        return
    if "GLOBALTALK RESUME IDENTITY R7I.2" not in text:
        die("R7I.2 must be present")
    if "GLOBALTALK PROGRESS TELEMETRY R7P" not in text:
        die("R7P must be present")

    text = insert_helper(text)
    text = patch_recursive(text)
    text = patch_direct_batch(text)
    write_text(path, text)

    print("Applied retry-existing R7Q: {}".format(path))
    print("  existing regular file with exact size+mtime skips data fork")
    print("  skipped files still refresh FinderInfo/resource metadata")
    print("  size or mtime mismatch overwrites from byte zero")
    print("  non-regular destination conflicts fail safely")
    print("  arbitrary partial files are never cross-process resumed")
    print("  AFP transport/retry/recovery behavior unchanged")


if __name__ == "__main__":
    main()
