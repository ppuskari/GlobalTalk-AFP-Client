#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# AFP 2.x servers do not implement the AFP extended-attribute commands used by
# the generic metadata copier. Some classic servers terminate or destabilize
# the session when those newer commands are attempted instead of simply
# returning kFPCallNotSupported. FinderInfo and resource forks are independent
# classic AFP metadata and must continue to work.
#
# Reject only generic xattr operations locally in afpsld when the negotiated
# AFP version is older than 3.0. The stateless metadata transfer layer already
# treats -ENOTSUP as an optional capability and continues with FinderInfo and
# resource-fork preservation.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "daemon", "commands.c")
MARKER = "GLOBALTALK CLASSIC AFP XATTR GATE R1"


def die(msg):
    raise SystemExit("apply_classic_xattr_gate: " + msg)


if not os.path.isfile(PATH):
    die("commands.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("Classic AFP xattr gate already applied: {}".format(UP))
    raise SystemExit(0)

old = '''    if (!volume_server_is_connected(volume)) {
        send_metadata_response(c, -ENOTCONN, NULL, 0, 0);
        afp_server_release(volume->server);
        return 0;
    }

    switch (request->header.command) {
'''

new = '''    if (!volume_server_is_connected(volume)) {
        send_metadata_response(c, -ENOTCONN, NULL, 0, 0);
        afp_server_release(volume->server);
        return 0;
    }

    /* GLOBALTALK CLASSIC AFP XATTR GATE R1
     * Generic extended attributes are AFP 3.x-era operations.  Do not put
     * those command codes on an AFP 2.x session: classic servers may close the
     * session rather than returning kFPCallNotSupported.  The metadata copier
     * treats ENOTSUP as optional and still preserves FinderInfo/resource fork.
     */
    if (volume->server->using_version
            && volume->server->using_version->av_number < 30
            && (request->header.command == AFP_SERVER_COMMAND_GETXATTR
                || request->header.command == AFP_SERVER_COMMAND_SETXATTR
                || request->header.command == AFP_SERVER_COMMAND_LISTXATTR
                || request->header.command == AFP_SERVER_COMMAND_REMOVEXATTR)) {
        send_metadata_response(c, -ENOTSUP, NULL, 0, 0);
        afp_server_release(volume->server);
        return 0;
    }

    switch (request->header.command) {
'''

count = text.count(old)
if count != 1:
    die("process_metadata insertion guard expected once, found {}".format(count))

text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied classic AFP xattr gate: {}".format(UP))
