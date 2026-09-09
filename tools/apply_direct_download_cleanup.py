#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Remove incomplete local data files and matching Netatalk AppleDouble
# sidecars after failed direct downloads.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D"


def die(msg):
    raise SystemExit("apply_direct_download_cleanup: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(
            what, count))
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_direct_download_cleanup.py "
            "NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")

    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)

    if MARKER in text:
        print("Direct download cleanup already applied: "
              "{}".format(path))
        return

    if "GLOBALTALK BATCH INTEGRITY R2" not in text:
        die("batch integrity R2 must be applied first")

    anchor = """static int retrieve_file(char * arg, int fd, struct stat *stat,
"""

    helper = r'''/* GLOBALTALK DIRECT DOWNLOAD CLEANUP R2D
 *
 * Direct archive pulls intentionally write into the final Netatalk backing
 * filesystem.  If a remote read, integrity check, or session close fails,
 * remove the incomplete data fork and any stale matching AppleDouble sidecar.
 */
static void cleanup_incomplete_local_file(const char *path)
{
    char work[PATH_MAX];
    char sidecar[PATH_MAX];
    char appledouble[PATH_MAX];
    char *slash;
    const char *base;
    const char *parent;
    int n;

    if (!path || path[0] == '\0') {
        return;
    }

    unlink(path);

    if (strlcpy(work, path, sizeof(work)) >= sizeof(work)) {
        return;
    }

    slash = strrchr(work, '/');

    if (slash) {
        base = slash + 1;
        *slash = '\0';
        parent = work[0] ? work : "/";
    } else {
        base = work;
        parent = ".";
    }

    if (base[0] == '\0') {
        return;
    }

    n = snprintf(appledouble, sizeof(appledouble),
                 "%s/.AppleDouble", parent);

    if (n < 0 || (size_t)n >= sizeof(appledouble)) {
        return;
    }

    n = snprintf(sidecar, sizeof(sidecar),
                 "%s/%s", appledouble, base);

    if (n < 0 || (size_t)n >= sizeof(sidecar)) {
        return;
    }

    unlink(sidecar);

    /* Remove an empty .AppleDouble directory, but leave it alone when
     * other valid sidecars are present. */
    rmdir(appledouble);
}

'''

    if text.count(anchor) != 1:
        die("retrieve_file anchor missing/non-unique")

    text = text.replace(anchor, helper + anchor, 1)

    old_recursive = """                if (file_ret < 0) {
                    ret = -1;
                    break;
                }

                bytes += amount;
"""

    new_recursive = """                if (file_ret < 0) {
                    cleanup_incomplete_local_file(new_local_path);
                    ret = -1;
                    break;
                }

                bytes += amount;
"""

    text = replace_once(
        text,
        old_recursive,
        new_recursive,
        "recursive partial cleanup")

    old_single = """            ret = retrieve_file(remote_path, fd, &st, &bytes_transferred);
            close(fd);

            if (ret == 0
"""

    new_single = """            ret = retrieve_file(remote_path, fd, &st, &bytes_transferred);
            close(fd);

            if (ret != 0) {
                cleanup_incomplete_local_file(dest_path);
            }

            if (ret == 0
"""

    text = replace_once(
        text,
        old_single,
        new_single,
        "single-file partial cleanup")

    write_text(path, text)

    print("Applied direct download cleanup R2D: {}".format(path))
    print("  failed data files are removed")
    print("  matching .AppleDouble sidecars are removed")
    print("  successful direct downloads are unchanged")


if __name__ == "__main__":
    main()
