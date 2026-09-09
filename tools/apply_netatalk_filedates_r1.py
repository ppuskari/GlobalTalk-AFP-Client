#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Preserve remote classic AFP creation/modification dates in the Netatalk
# AppleDouble File Dates Info entry (entry ID 8) during direct downloads.
#
# Netatalk Client 0.9.5 already maps the remote AFP creation date into the
# returned struct stat st_ctime and the modification date into st_mtime.  Its
# normal local POSIX finalizer restores st_mtime, but its metadata helpers
# intentionally copy only FinderInfo/resource forks/xattrs.  In -M netatalk
# mode that leaves the 16-byte AppleDouble File Dates Info entry unpopulated.
# Classic Finder therefore sees an unset creation date and may later see a
# Netatalk-generated current modification date instead of the source dates.
#
# This overlay writes only the first two 32-bit fields of entry ID 8:
#   +0  create
#   +4  modify
# Backup/access remain untouched.  No AFP/ASP/ATP transport code is changed.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK NETATALK FILEDATES R1"


def die(msg):
    raise SystemExit("apply_netatalk_filedates_r1: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_netatalk_filedates_r1.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")

    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)

    if MARKER in text:
        print("Netatalk File Dates R1 already applied: {}".format(path))
        return

    func_anchor = "static int copy_remote_metadata_to_local("
    start = text.find(func_anchor)

    if start < 0:
        die("copy_remote_metadata_to_local anchor missing")

    # Isolate only this function so the insertion remains guarded even if
    # neighboring Netatalk Client code changes slightly.
    next_func = text.find("\nstatic int ", start + len(func_anchor))

    if next_func < 0:
        die("could not locate end of copy_remote_metadata_to_local")

    block = text[start:next_func]

    if "afp_sl_metadata_copy_remote_to_local" not in block:
        die("remote metadata copy call missing from target function")

    helper = r'''/* GLOBALTALK NETATALK FILEDATES R1
 *
 * Netatalk AppleDouble v2 File Dates Info (entry ID 8) stores four network-
 * order 32-bit dates relative to 2000-01-01.  Preserve the source AFP create
 * and modify dates after FinderInfo/resource metadata has created the sidecar.
 * The remote low-level stat path already maps AFP create -> st_ctime and
 * AFP modify -> st_mtime, so no additional AFP transaction is required.
 */
#define GT_AD_MAGIC             0x00051607UL
#define GT_AD_FILEDATES_ID      8UL
#define GT_AD_HEADER_SIZE       26U
#define GT_AD_ENTRY_SIZE        12U
#define GT_AD_DATE_DELTA        946684800LL

static uint32_t gt_ad_be32(const unsigned char *p)
{
    return ((uint32_t)p[0] << 24)
           | ((uint32_t)p[1] << 16)
           | ((uint32_t)p[2] << 8)
           | (uint32_t)p[3];
}

static uint16_t gt_ad_be16(const unsigned char *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | (uint16_t)p[1]);
}

static void gt_ad_put_be32(unsigned char *p, uint32_t value)
{
    p[0] = (unsigned char)(value >> 24);
    p[1] = (unsigned char)(value >> 16);
    p[2] = (unsigned char)(value >> 8);
    p[3] = (unsigned char)value;
}

static int gt_netatalk_sidecar_path(const char *path,
                                    char *sidecar, size_t size)
{
    struct stat local_st;
    const char *slash;
    const char *base;
    size_t dirlen;
    int n;

    if (!path || !sidecar || size == 0) {
        return -EINVAL;
    }

    if (lstat(path, &local_st) < 0) {
        return -errno;
    }

    if (S_ISDIR(local_st.st_mode)) {
        n = snprintf(sidecar, size, "%s/.AppleDouble/.Parent", path);
    } else {
        slash = strrchr(path, '/');
        base = slash ? slash + 1 : path;
        dirlen = slash ? (size_t)(slash - path + 1) : 0;

        if (base[0] == '\0' || dirlen > (size_t)INT_MAX) {
            return -EINVAL;
        }

        n = snprintf(sidecar, size, "%.*s.AppleDouble/%s",
                     (int)dirlen, path, base);
    }

    if (n < 0 || (size_t)n >= size) {
        return -ENAMETOOLONG;
    }

    return 0;
}

static int gt_preserve_netatalk_filedates(const char *local_path,
        const struct stat *remote_st)
{
    unsigned char header[GT_AD_HEADER_SIZE];
    unsigned char entry[GT_AD_ENTRY_SIZE];
    unsigned char dates[8];
    char sidecar[PATH_MAX];
    uint16_t count;
    uint32_t date_offset = 0;
    uint32_t date_length = 0;
    uint32_t create_raw;
    uint32_t modify_raw;
    int fd = -1;
    int ret;

    if (transfer_metadata_mode != AFP_METADATA_NETATALK) {
        return 0;
    }

    if (!remote_st) {
        return -EINVAL;
    }

    ret = gt_netatalk_sidecar_path(local_path, sidecar, sizeof(sidecar));

    if (ret < 0) {
        return ret;
    }

    fd = open(sidecar, O_RDWR);

    if (fd < 0) {
        return -errno;
    }

    if (pread(fd, header, sizeof(header), 0) != (ssize_t)sizeof(header)) {
        ret = -EIO;
        goto out;
    }

    if (gt_ad_be32(header) != GT_AD_MAGIC) {
        ret = -EINVAL;
        goto out;
    }

    count = gt_ad_be16(header + 24);

    if (count == 0 || count > 32) {
        ret = -EINVAL;
        goto out;
    }

    for (uint16_t i = 0; i < count; i++) {
        off_t off = (off_t)GT_AD_HEADER_SIZE
                    + (off_t)i * (off_t)GT_AD_ENTRY_SIZE;

        if (pread(fd, entry, sizeof(entry), off)
                != (ssize_t)sizeof(entry)) {
            ret = -EIO;
            goto out;
        }

        if (gt_ad_be32(entry) == GT_AD_FILEDATES_ID) {
            date_offset = gt_ad_be32(entry + 4);
            date_length = gt_ad_be32(entry + 8);
            break;
        }
    }

    if (date_offset == 0 || date_length < 16) {
        ret = -EINVAL;
        goto out;
    }

    /* Netatalk's AD_DATE_FROM_UNIX(x) is htonl(x - 946684800).
     * Cast after the signed subtraction so pre-2000 dates retain their
     * intended two's-complement 32-bit representation. */
    create_raw = (uint32_t)((int64_t)remote_st->st_ctime
                            - GT_AD_DATE_DELTA);
    modify_raw = (uint32_t)((int64_t)remote_st->st_mtime
                            - GT_AD_DATE_DELTA);
    gt_ad_put_be32(dates, create_raw);
    gt_ad_put_be32(dates + 4, modify_raw);

    if (pwrite(fd, dates, sizeof(dates), (off_t)date_offset)
            != (ssize_t)sizeof(dates)) {
        ret = -EIO;
        goto out;
    }

    ret = 0;
out:
    close(fd);
    return ret;
}

'''

    text = text[:start] + helper + text[start:]

    # Re-locate the function after helper insertion.
    start = text.find(func_anchor, start + len(helper))
    next_func = text.find("\nstatic int ", start + len(func_anchor))

    if start < 0 or next_func < 0:
        die("target function disappeared after helper insertion")

    block = text[start:next_func]

    call = r'''    /* GLOBALTALK NETATALK FILEDATES R1 */
    ret = gt_preserve_netatalk_filedates(local_path, st);

    if (ret < 0) {
        return ret;
    }

'''

    # Netatalk Client revisions have ended this helper either with a plain
    # return 0 or by chaining directly into the POSIX metadata finalizer.
    # Insert immediately before the final return in either shape.
    pos = block.rfind("    return ")

    if pos < 0:
        die("final return missing from copy_remote_metadata_to_local")

    if call.strip() in block:
        die("File Dates call unexpectedly already present")

    block = block[:pos] + call + block[pos:]
    text = text[:start] + block + text[next_func:]

    write_text(path, text)

    print("Applied Netatalk File Dates R1: {}".format(path))
    print("  AFP creation date -> AppleDouble entry 8 +0")
    print("  AFP modification date -> AppleDouble entry 8 +4")
    print("  backup/access date words are preserved")
    print("  existing POSIX mtime finalization is unchanged")


if __name__ == "__main__":
    main()
