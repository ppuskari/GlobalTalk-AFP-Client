#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Make Netatalk Client 0.9.5's stateless daemon accept ASP/DDP-backed
# servers as connected even though they do not use a DSI TCP descriptor.
# Written for Python 3.4 compatibility.

from __future__ import print_function

import io
import os
import sys


def die(msg):
    raise SystemExit("apply_daemon_asp_compat: " + msg)


def patch_file(path):
    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()

    changed = False

    old = "           && volume->server->fd >= 0;"
    new = "           && (volume->server->fd >= 0 || volume->server->asp);"
    if new not in text:
        if text.count(old) != 1:
            die("volume connected guard missing/non-unique")
        text = text.replace(old, new, 1)
        changed = True

    old = "|| s->fd < 0) {"
    new = "|| (s->fd < 0 && !s->asp)) {"
    if new not in text:
        count = text.count(old)
        if count != 3:
            die("expected 3 s->fd guards, found {}".format(count))
        text = text.replace(old, new)
        changed = True

    old = "            || server->fd < 0) {"
    new = "            || (server->fd < 0 && !server->asp)) {"
    if new not in text:
        if text.count(old) != 1:
            die("server->fd guard missing/non-unique")
        text = text.replace(old, new, 1)
        changed = True

    if changed:
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)

    print("ASP stateless-daemon compatibility ready: {}".format(path))


def main():
    if len(sys.argv) != 2:
        die("usage: apply_daemon_asp_compat.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "daemon", "commands.c")
    if not os.path.isfile(path):
        die("not a Netatalk Client tree: {}".format(root))

    patch_file(path)


if __name__ == "__main__":
    main()
