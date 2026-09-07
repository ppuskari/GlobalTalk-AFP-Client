#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R4 performance overlay for pinned Netatalk Client 0.9.5.
#
# R3 proved resource-fork correctness but the metadata helper still reopened
# the remote resource fork for every 16 KiB metadata chunk.  R4 exposes a
# stateful resource-fork open through the existing stateless file-handle API,
# then makes remote-to-local metadata copies use open/read/close exactly like
# ordinary data-fork copies.
#
# The streamed read size is 101728 bytes = 22 * the proven 4624-byte ASP
# response ceiling.  This keeps the fork open while ll_read() performs the
# individual ASP reads and avoids an unnecessary partial ASP transaction at
# each client-side IPC boundary.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RFORK R4 STATEFUL STREAM"
STREAM_CHUNK = 101728


def die(msg):
    raise SystemExit("apply_rfork_r4_stream: " + msg)


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


def patch_server_header(path):
    text = read_text(path)
    if MARKER in text:
        return
    old = """struct afp_server_open_request {\n    struct afp_server_request_header header;\n    volumeid_t volumeid;\n    char path[AFP_MAX_PATH];\n    int mode;\n};\n"""
    new = """struct afp_server_open_request {\n    struct afp_server_request_header header;\n    volumeid_t volumeid;\n    char path[AFP_MAX_PATH];\n    int mode;\n    /* GLOBALTALK RFORK R4 STATEFUL STREAM */\n    unsigned int resource;\n};\n"""
    text = replace_once(text, old, new, path)
    write_text(path, text)


def patch_afpsl_header(path):
    text = read_text(path)
    if "afp_sl_open_resourcefork" in text:
        return
    old = """int afp_sl_open(volumeid_t * volid, const char * path,\n                struct afp_url * url, unsigned int *fileid,\n                unsigned int mode);\n"""
    new = old + """/* GLOBALTALK RFORK R4 STATEFUL STREAM */\nint afp_sl_open_resourcefork(volumeid_t *volid, const char *path,\n                             struct afp_url *url, unsigned int *fileid,\n                             unsigned int mode);\n"""
    if old not in text:
        # Some 0.9.5 snapshots use tighter pointer spacing.
        old = """int afp_sl_open(volumeid_t *volid, const char *path, struct afp_url *url,\n                unsigned int *fileid, unsigned int mode);\n"""
        new = old + """/* GLOBALTALK RFORK R4 STATEFUL STREAM */\nint afp_sl_open_resourcefork(volumeid_t *volid, const char *path,\n                             struct afp_url *url, unsigned int *fileid,\n                             unsigned int mode);\n"""
    text = replace_once(text, old, new, path)
    write_text(path, text)


def patch_midlevel_header(path):
    text = read_text(path)
    if "ml_open_resourcefork" in text:
        return
    old = """int ml_open(struct afp_volume * volume, const char *path, int flags,\n            struct afp_file_info **newfp);\n"""
    new = old + """/* GLOBALTALK RFORK R4 STATEFUL STREAM */\nint ml_open_resourcefork(struct afp_volume *volume, const char *path,\n                         int flags, struct afp_file_info **newfp);\n"""
    text = replace_once(text, old, new, path)
    write_text(path, text)


def patch_midlevel(path):
    text = read_text(path)
    if "int ml_open_resourcefork(" in text:
        return
    start, end = function_span(text, "static int open_appledouble_meta(")
    helper = r'''

/* GLOBALTALK RFORK R4 STATEFUL STREAM
 * Open the real AFP resource fork once and return an ordinary daemon file
 * handle.  Subsequent afp_sl_read() calls therefore use the same forkid that
 * ll_read() already uses for stateful data-fork transfers. */
int ml_open_resourcefork(struct afp_volume *volume, const char *path,
                         int flags, struct afp_file_info **newfp)
{
    struct afp_file_info *fp;
    int ret;

    if (!volume || !path || !newfp) {
        return -EINVAL;
    }

    fp = calloc(1, sizeof(*fp));
    if (!fp) {
        return -ENOMEM;
    }

    ret = open_appledouble_meta(volume, path, AFP_META_RESOURCE, flags, fp);
    if (ret < 0) {
        free(fp);
        return ret;
    }

    *newfp = fp;
    return 0;
}
'''
    text = text[:end] + helper + text[end:]
    write_text(path, text)


def patch_stateless(path):
    text = read_text(path)
    if "int afp_sl_open_resourcefork(" in text:
        return

    start, end = function_span(text, "int afp_sl_open(")
    original = text[start:end]
    if "request.mode = mode;" not in original:
        die("{}: afp_sl_open mode assignment missing".format(path))

    original = original.replace(
        "    request.mode = mode;\n",
        "    request.mode = mode;\n"
        "    request.resource = 0;\n",
        1)

    clone = original.replace(
        "int afp_sl_open(",
        "int afp_sl_open_resourcefork(",
        1)
    clone = clone.replace(
        "    request.resource = 0;\n",
        "    request.resource = 1;\n",
        1)
    clone = ("\n\n/* {} */\n".format(MARKER) + clone)

    text = text[:start] + original + clone + text[end:]
    write_text(path, text)


def patch_commands(path):
    text = read_text(path)
    if "ml_open_resourcefork(v, request->path" in text:
        return
    old = "    ret = ml_open(v, request->path, request->mode, &fp);\n"
    new = """    /* GLOBALTALK RFORK R4 STATEFUL STREAM */\n    if (request->resource > 1) {\n        result = AFP_SERVER_RESULT_ERROR;\n        goto done;\n    }\n\n    if (request->resource) {\n        ret = ml_open_resourcefork(v, request->path, request->mode, &fp);\n    } else {\n        ret = ml_open(v, request->path, request->mode, &fp);\n    }\n"""
    text = replace_once(text, old, new, path)
    write_text(path, text)


def patch_metadata(path):
    text = read_text(path)
    if "stream_remote_resourcefork_to_local" in text:
        return

    signature = "int afp_sl_metadata_copy_remote_to_local("
    func_start, func_end = function_span(text, signature)
    func = text[func_start:func_end]

    query = "ret = afp_sl_getresourcefork(source_volume, source_path, NULL, 0, 0);"
    qpos = func.find(query)
    if qpos < 0:
        die("{}: resource size query not found".format(path))

    ifpos = func.find("if (ret > 0) {", qpos)
    if ifpos < 0:
        die("{}: positive resource-size block not found".format(path))

    # Find the matching brace for the if block inside the extracted function.
    sub = func[ifpos:]
    brace = sub.find("{")
    depth = 0
    block_end = None
    for i in range(brace, len(sub)):
        if sub[i] == "{":
            depth += 1
        elif sub[i] == "}":
            depth -= 1
            if depth == 0:
                block_end = ifpos + i + 1
                break
    if block_end is None:
        die("{}: unterminated resource transfer block".format(path))

    replacement = r'''if (ret > 0) {
        unsigned long long total = (unsigned int)ret;
        ret = stream_remote_resourcefork_to_local(source_volume, source_path,
                local_path, mode, total, warnings);
        if (ret < 0) {
            return ret;
        }
        offset = total;
    }'''
    func = func[:ifpos] + replacement + func[block_end:]

    helper = r'''

#define R4_RESOURCE_STREAM_CHUNK 101728U

/* GLOBALTALK RFORK R4 STATEFUL STREAM
 *
 * The old metadata path called afp_sl_getresourcefork() once per metadata
 * chunk.  That command resolves the path and opens/closes the AFP resource
 * fork on every call.  Use the existing stateful afpsld file-handle/read path
 * instead, exactly as ordinary data-fork downloads do.
 *
 * 101728 = 22 * 4624, so each full client-side request is an exact number of
 * transactions at the proven ASP response ceiling. */
static int stream_remote_resourcefork_to_local(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode mode,
    unsigned long long total, unsigned int *warnings)
{
    unsigned char *buffer = NULL;
    unsigned long long offset = 0;
    unsigned int fileid = 0;
    int opened = 0;
    int ret = 0;

    buffer = malloc(R4_RESOURCE_STREAM_CHUNK);
    if (!buffer) {
        return -ENOMEM;
    }

    ret = afp_sl_open_resourcefork(source_volume, source_path, NULL,
                                   &fileid, O_RDONLY);
    if (ret < 0) {
        free(buffer);
        return ret;
    }
    opened = 1;

    while (offset < total) {
        unsigned long long remaining = total - offset;
        unsigned int chunk = R4_RESOURCE_STREAM_CHUNK;
        unsigned int received = 0;
        unsigned int eof = 0;
        int write_ret;

        if (remaining < chunk) {
            chunk = (unsigned int)remaining;
        }

        ret = afp_sl_read(source_volume, fileid, 1, offset, chunk,
                          &received, &eof, (char *)buffer);
        if (ret != 0) {
            goto done;
        }
        if (received == 0 || received > chunk) {
            ret = -EIO;
            goto done;
        }

        write_ret = local_resourcefork_write(local_path, mode, buffer,
                                              received, (off_t)offset);
        if (transfer_error_unsupported(write_ret)) {
            transfer_warning(warnings, AFP_METADATA_WARNING_UNSUPPORTED);
            ret = 0;
            goto done;
        }
        if (write_ret < 0) {
            ret = write_ret;
            goto done;
        }

        offset += received;
        if (eof && offset < total) {
            ret = -EIO;
            goto done;
        }
    }

done:
    if (opened) {
        int close_ret = afp_sl_close(source_volume, fileid);
        if (ret == 0 && close_ret < 0) {
            ret = close_ret;
        }
    }
    free(buffer);
    return ret;
}
'''

    text = text[:func_start] + helper + "\n" + func + text[func_end:]
    write_text(path, text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_rfork_r4_stream.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    paths = {
        "server_h": os.path.join(root, "include", "afp_server.h"),
        "afpsl_h": os.path.join(root, "include", "afpsl.h"),
        "mid_h": os.path.join(root, "include", "midlevel.h"),
        "mid_c": os.path.join(root, "lib", "midlevel.c"),
        "stateless": os.path.join(root, "daemon", "stateless.c"),
        "commands": os.path.join(root, "daemon", "commands.c"),
        "metadata": os.path.join(root, "daemon", "metadata.c"),
    }

    for path in paths.values():
        if not os.path.isfile(path):
            die("required pinned source missing: {}".format(path))

    patch_server_header(paths["server_h"])
    patch_afpsl_header(paths["afpsl_h"])
    patch_midlevel_header(paths["mid_h"])
    patch_midlevel(paths["mid_c"])
    patch_stateless(paths["stateless"])
    patch_commands(paths["commands"])
    patch_metadata(paths["metadata"])

    print("R4 stateful resource-fork stream ready: {}".format(root))
    print("  stream chunk: {} bytes (22 * 4624)".format(STREAM_CHUNK))


if __name__ == "__main__":
    main()
