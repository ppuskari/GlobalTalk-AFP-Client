#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Tighten remote ResourceFork downloads in Netatalk Client 0.9.5.
#
# The stock stateless metadata helper re-opens the remote ResourceFork for
# every 4096-byte chunk. That is cheap over AFP/TCP but expensive over
# classic ASP/DDP. Add an internal open modifier so afpsld can keep one
# resource-fork handle open and let the existing afp_sl_read() path stream it.
# Written for Python 3.4 compatibility.

from __future__ import print_function

import io
import os
import sys


def die(msg):
    raise SystemExit("apply_pull_perf: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, label):
    if new in text:
        return text, False
    count = text.count(old)
    if count != 1:
        die("{} anchor missing/non-unique (found {})".format(label, count))
    return text.replace(old, new, 1), True


def patch_afpsl(root):
    path = os.path.join(root, "include", "afpsl.h")
    text = read_text(path)
    old = (
        "#define AFP_SL_METADATA_CHUNK 4096\n\n"
        "/* Maximum returned xattr name list."
    )
    new = (
        "#define AFP_SL_METADATA_CHUNK 4096\n\n"
        "/* Private modifier for afpsld's existing OPEN request. The daemon\n"
        " * strips this bit before passing POSIX flags to the AFP layer. */\n"
        "#define AFP_SL_OPEN_RESOURCE 0x40000000U\n\n"
        "/* Maximum returned xattr name list."
    )
    text, changed = replace_once(text, old, new, "afpsl open-resource flag")
    if changed:
        write_text(path, text)


def patch_midlevel_header(root):
    path = os.path.join(root, "include", "midlevel.h")
    text = read_text(path)
    old = (
        "int ml_open(struct afp_volume * volume, const char *path, int flags,\n"
        "            struct afp_file_info **newfp);\n\n"
        "int ml_creat("
    )
    new = (
        "int ml_open(struct afp_volume * volume, const char *path, int flags,\n"
        "            struct afp_file_info **newfp);\n\n"
        "int ml_open_resource(struct afp_volume * volume, const char *path,\n"
        "                     int flags, struct afp_file_info **newfp);\n\n"
        "int ml_creat("
    )
    text, changed = replace_once(text, old, new, "midlevel resource prototype")
    if changed:
        write_text(path, text)


def patch_midlevel_source(root):
    path = os.path.join(root, "lib", "midlevel.c")
    text = read_text(path)
    if "int ml_open_resource(" in text:
        return

    old = (
        "static int open_appledouble_meta(struct afp_volume *volume, const char *path,\n"
        "                                 unsigned int resource, int flags,\n"
        "                                 struct afp_file_info *fp)\n"
        "{\n"
        "    char converted_path[AFP_MAX_PATH];\n\n"
        "    if (!volume || !path || !fp) {\n"
        "        return -EINVAL;\n"
        "    }\n\n"
        "    if (convert_path_to_afp(volume->server->path_encoding,\n"
        "                            converted_path, (char *) path, AFP_MAX_PATH)) {\n"
        "        return -EINVAL;\n"
        "    }\n\n"
        "    if (invalid_filename(volume->server, converted_path)) {\n"
        "        return -ENAMETOOLONG;\n"
        "    }\n\n"
        "    return appledouble_open_meta(volume, converted_path, resource, flags, fp);\n"
        "}\n"
    )
    new = old + (
        "\n"
        "int ml_open_resource(struct afp_volume *volume, const char *path,\n"
        "                     int flags, struct afp_file_info **newfp)\n"
        "{\n"
        "    struct afp_file_info *fp;\n"
        "    int ret;\n\n"
        "    if (!newfp) {\n"
        "        return -EINVAL;\n"
        "    }\n\n"
        "    *newfp = NULL;\n"
        "    fp = malloc(sizeof(*fp));\n\n"
        "    if (!fp) {\n"
        "        return -ENOMEM;\n"
        "    }\n\n"
        "    ret = open_appledouble_meta(volume, path, AFP_META_RESOURCE,\n"
        "                                flags, fp);\n\n"
        "    if (ret < 0) {\n"
        "        free(fp);\n"
        "        return ret;\n"
        "    }\n\n"
        "    *newfp = fp;\n"
        "    return 0;\n"
        "}\n"
    )
    text, changed = replace_once(text, old, new, "midlevel resource opener")
    if changed:
        write_text(path, text)


def patch_commands(root):
    path = os.path.join(root, "daemon", "commands.c")
    text = read_text(path)
    if "ml_open_resource(v, request->path" in text:
        return

    old = (
        "    log_for_client((void *) c, AFPFSD, LOG_DEBUG, \"Opening file '%s' mode=%d\",\n"
        "                   request->path, request->mode);\n"
        "    ret = ml_open(v, request->path, request->mode, &fp);\n"
    )
    new = (
        "    int open_mode = request->mode;\n"
        "    int resource_open = (open_mode & AFP_SL_OPEN_RESOURCE) != 0;\n"
        "    open_mode &= ~AFP_SL_OPEN_RESOURCE;\n"
        "    log_for_client((void *) c, AFPFSD, LOG_DEBUG,\n"
        "                   \"Opening file '%s' mode=%d resource=%d\",\n"
        "                   request->path, open_mode, resource_open);\n\n"
        "    if (resource_open) {\n"
        "        ret = ml_open_resource(v, request->path, open_mode, &fp);\n"
        "    } else {\n"
        "        ret = ml_open(v, request->path, open_mode, &fp);\n"
        "    }\n"
    )
    text, changed = replace_once(text, old, new, "daemon resource open")
    if changed:
        write_text(path, text)


def patch_metadata(root):
    path = os.path.join(root, "daemon", "metadata.c")
    text = read_text(path)
    marker = "afp_sl_read(source_volume, resource_fileid, 1,"
    if marker in text:
        return

    start_marker = (
        "int afp_sl_metadata_copy_remote_to_local(\n"
        "    volumeid_t *source_volume, const char *source_path,\n"
    )
    end_marker = "\nstatic int transfer_remote_xattrs_to_remote("
    start = text.find(start_marker)
    if start < 0:
        die("remote-to-local metadata function start missing")
    end = text.find(end_marker, start)
    if end < 0:
        die("remote-to-local metadata function end missing")

    new_function = r'''int afp_sl_metadata_copy_remote_to_local(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode mode,
    unsigned int *warnings)
{
    unsigned char finderinfo[32];
    unsigned char buffer[AFP_SL_METADATA_CHUNK];
    unsigned long long offset = 0;
    unsigned int resource_fileid = 0;
    int finder_ret;
    int resource_ret;
    int ret;

    if (warnings) {
        *warnings = AFP_METADATA_WARNING_NONE;
    }

    if (!source_volume || !*source_volume || !source_path || !local_path
            || !metadata_mode_valid(mode)) {
        return -EINVAL;
    }

    if (mode == AFP_METADATA_NONE) {
        return 0;
    }

    /*
     * Ask for the resource-fork size first so the first post-data-fork AFP
     * operation is directly related to the next fork. The stock 0.9.5 path
     * fetched FinderInfo first, producing a visible quiet gap on ASP/DDP.
     */
    resource_ret = afp_sl_getresourcefork(source_volume, source_path,
                                          NULL, 0, 0);

    if (resource_ret < 0) {
        ret = transfer_metadata_result(resource_ret, warnings);

        if (ret < 0) {
            return ret;
        }
    }

    ret = afp_metadata_clear_local(local_path, mode, warnings);

    if (ret < 0) {
        return ret;
    }

    /*
     * Keep one remote resource-fork handle open for the whole copy. The
     * original helper called afp_sl_getresourcefork() for every 4 KiB chunk;
     * each call performed a fresh getattr/open/read/close sequence.
     */
    if (resource_ret > 0) {
        unsigned long long total = (unsigned int)resource_ret;

        ret = afp_sl_open(source_volume, source_path, NULL,
                          &resource_fileid,
                          O_RDONLY | AFP_SL_OPEN_RESOURCE);

        if (ret < 0) {
            return ret;
        }

        while (offset < total) {
            size_t chunk = (size_t)(total - offset);
            unsigned int received = 0;
            unsigned int eof = 0;
            int write_ret;

            if (chunk > sizeof(buffer)) {
                chunk = sizeof(buffer);
            }

            ret = afp_sl_read(source_volume, resource_fileid, 1,
                              offset, (unsigned int)chunk,
                              &received, &eof, (char *)buffer);

            if (ret != 0 || received == 0 || received > chunk) {
                int read_ret = ret != 0 ? ret : -EIO;
                (void)afp_sl_close(source_volume, resource_fileid);
                return read_ret;
            }

            write_ret = local_resourcefork_write(local_path, mode, buffer,
                                                  received, (off_t)offset);

            if (transfer_error_unsupported(write_ret)) {
                transfer_warning(warnings, AFP_METADATA_WARNING_UNSUPPORTED);
                break;
            }

            if (write_ret < 0) {
                (void)afp_sl_close(source_volume, resource_fileid);
                return write_ret;
            }

            offset += received;

            if (eof && offset < total) {
                (void)afp_sl_close(source_volume, resource_fileid);
                return -EIO;
            }
        }

        ret = afp_sl_close(source_volume, resource_fileid);
        resource_fileid = 0;

        if (ret < 0) {
            return ret;
        }
    }

    /*
     * FinderInfo and generic xattrs follow the ResourceFork. This preserves
     * all metadata while keeping the fork-to-fork transition on the wire tight.
     */
    finder_ret = afp_sl_getfinderinfo(source_volume, source_path, finderinfo,
                                      sizeof(finderinfo));

    if (finder_ret >= 0 && finder_ret != (int)sizeof(finderinfo)) {
        return -EIO;
    }

    if (finder_ret < 0 && !transfer_error_absent(finder_ret)
            && !transfer_error_unsupported(finder_ret)) {
        return finder_ret;
    }

    if (finder_ret == (int)sizeof(finderinfo)) {
        ret = local_finderinfo_set(local_path, mode, finderinfo);
    } else {
        ret = finder_ret;
    }

    ret = transfer_metadata_result(ret, warnings);

    if (ret < 0) {
        return ret;
    }

    return transfer_remote_xattrs_to_local(source_volume, source_path,
                                           local_path, mode, warnings);
}
'''
    text = text[:start] + new_function + text[end:]
    write_text(path, text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_pull_perf.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    required = (
        os.path.join(root, "include", "afpsl.h"),
        os.path.join(root, "include", "midlevel.h"),
        os.path.join(root, "lib", "midlevel.c"),
        os.path.join(root, "daemon", "commands.c"),
        os.path.join(root, "daemon", "metadata.c"),
    )

    for path in required:
        if not os.path.isfile(path):
            die("not a Netatalk Client 0.9.5 tree: {}".format(root))

    patch_afpsl(root)
    patch_midlevel_header(root)
    patch_midlevel_source(root)
    patch_commands(root)
    patch_metadata(root)
    print("Pull-path ResourceFork streaming ready: {}".format(root))


if __name__ == "__main__":
    main()
