#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Pinned Netatalk Client 0.9.5 compatibility companion for R7G.
# The 0.9.5 ml_open() path API uses a fixed AFP_MAX_PATH buffer rather than
# the later allocation helper.  Keep the R7G semantics but mirror 0.9.5 exactly.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK KNOWN DATA OPEN R7G"
PIN_MARKER = "GLOBALTALK KNOWN DATA OPEN R7G PIN095"


def die(msg):
    raise SystemExit("apply_known_data_open_r7g_pin095: " + msg)


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


def main():
    if len(sys.argv) != 2:
        die("usage: apply_known_data_open_r7g_pin095.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "lib", "midlevel.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if PIN_MARKER in text:
        print("R7G pinned-0.9.5 compatibility already applied")
        return
    if MARKER not in text:
        die("R7G must be applied first")

    start, end = function_span(text, "int ml_open_known_data(")
    replacement = r'''/* GLOBALTALK KNOWN DATA OPEN R7G PIN095
 * Pinned Netatalk Client 0.9.5 uses the fixed-buffer path conversion API. */
int ml_open_known_data(struct afp_volume *volume, const char *path, int flags,
                       unsigned long long known_size,
                       struct afp_file_info **newfp)
{
    struct afp_file_info *fp;
    int ret;
    unsigned int dirid;
    char converted_path[AFP_MAX_PATH];

    if (convert_path_to_afp(volume->server->path_encoding,
                            converted_path, (char *)path, AFP_MAX_PATH)) {
        return -EINVAL;
    }

    if (invalid_filename(volume->server, converted_path)) {
        return -ENAMETOOLONG;
    }

    if (volume_is_readonly(volume) &&
            (flags & (O_WRONLY | O_RDWR | O_TRUNC | O_APPEND | O_CREAT))) {
        return -EACCES;
    }

    fp = malloc(sizeof(*fp));
    if (!fp) {
        return -ENOMEM;
    }

    *newfp = fp;
    memset(fp, 0, sizeof(*fp));
    ret = appledouble_open(volume, path, flags, fp);
    if (ret < 0) {
        free(fp);
        return ret;
    }

    if (ret == 1) {
        goto out;
    }

    if (get_dirid(volume, converted_path, fp->basename, &dirid) < 0) {
        ret = -ENOENT;
        goto error;
    }

    fp->did = dirid;
    fp->size = known_size;
    fp->r7g_known_size_valid = 1;
    ret = ll_open(volume, converted_path, flags, fp);
    if (ret < 0) {
        goto error;
    }

out:
    return 0;
error:
    free(fp);
    return ret;
}'''

    text = text[:start] + replacement + text[end:]
    write_text(path, text)
    print("Applied R7G pinned Netatalk Client 0.9.5 path compatibility")


if __name__ == "__main__":
    main()
