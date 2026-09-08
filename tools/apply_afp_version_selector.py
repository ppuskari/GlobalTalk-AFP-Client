#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Backport explicit AFP version selection to pinned Netatalk Client 0.9.5.
# The default requested_version=0 behavior is unchanged.  This is intentionally
# small and mirrors the later upstream cmdline API shape.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK AFP VERSION SELECTOR"


def die(msg):
    raise SystemExit("apply_afp_version_selector: " + msg)


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


def main():
    if len(sys.argv) != 2:
        die("usage: apply_afp_version_selector.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    c_path = os.path.join(root, "cmdline", "cmdline_afp.c")
    h_path = os.path.join(root, "cmdline", "cmdline_afp.h")

    if not os.path.isfile(c_path) or not os.path.isfile(h_path):
        die("not a Netatalk Client tree: {}".format(root))

    c_text = read_text(c_path)
    h_text = read_text(h_path)

    if MARKER not in h_text:
        old = "int cmdline_afp_setup(int batch_mode, char * url_string);"
        new = (
            "/* {} */\n"
            "int cmdline_afp_setup(int batch_mode, char * url_string,\n"
            "                      int requested_version);"
        ).format(MARKER)
        h_text = replace_once(h_text, old, new, h_path)
        write_text(h_path, h_text)

    if MARKER not in c_text:
        old = "int cmdline_afp_setup(int batch_mode, char * url_string)\n{"
        new = (
            "/* {} */\n"
            "int cmdline_afp_setup(int batch_mode, char * url_string,\n"
            "                      int requested_version)\n{{"
        ).format(MARKER)
        c_text = replace_once(c_text, old, new, c_path)

        old = (
            "            if (afp_parse_url(&url, url_string)) {\n"
            "                printf(\"Could not parse url.\\n\");\n"
            "                return -1;\n"
            "            }\n"
        )
        new = old + (
            "\n"
            "            /* Explicit compatibility probe for legacy AFP servers. */\n"
            "            if (requested_version) {\n"
            "                url.requested_version = requested_version;\n"
            "            }\n"
        )
        c_text = replace_once(c_text, old, new, c_path)
        write_text(c_path, c_text)

    print("AFP version selector ready: {}".format(root))


if __name__ == "__main__":
    main()
