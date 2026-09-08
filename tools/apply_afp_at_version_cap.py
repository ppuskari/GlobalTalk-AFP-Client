#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Keep automatic AFP version selection transport-correct for classic ASP/DDP.
# Netatalk Client 0.9.5 normally picks the highest recognized version returned
# by FPGetSrvrInfo/GetStatus.  Some dual-stack servers advertise AFP 3.x for
# their TCP/DSI service while also answering the same status request over ASP.
# AFP over classic AppleTalk/ASP must therefore auto-negotiate within AFP 2.x.
#
# Explicit requested_version values are left unchanged.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK ASP AUTO AFP CAP 2.2"


def die(msg):
    raise SystemExit("apply_afp_at_version_cap: " + msg)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_afp_at_version_cap.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "lib", "server.c")

    if not os.path.isfile(path):
        die("not a Netatalk Client tree: {}".format(root))

    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if MARKER in text:
        print("ASP AFP auto-version cap already applied: {}".format(root))
        return

    old = """    /* Figure out what version we're using */\n    if (((server->using_version =\n                pick_version(versions, requested_version)) == NULL)) {\n        log_for_client(priv, AFPFSD, LOG_ERR,\n                       \"Server cannot handle AFP version %d\",\n                       requested_version);\n        errno = EPROTONOSUPPORT;\n        goto error;\n    }\n"""

    new = """    /* GLOBALTALK ASP AUTO AFP CAP 2.2\n     *\n     * GetStatus can advertise versions belonging to a server's TCP/DSI\n     * service as well as its classic AppleTalk service.  Netatalk Client's\n     * generic auto picker selects the highest recognized advertised version,\n     * which can incorrectly choose AFP 3.x for an ASP/DDP session.\n     *\n     * For automatic negotiation on ASP only, select from the advertised\n     * versions at or below AFP 2.2.  Explicit -A requests remain unchanged.\n     */\n    if (server->asp && requested_version == 0) {\n        unsigned char asp_versions[SERVER_MAX_VERSIONS];\n        int src;\n        int dst = 0;\n\n        memset(asp_versions, 0, sizeof(asp_versions));\n        for (src = 0; src < SERVER_MAX_VERSIONS && versions[src]; src++) {\n            if (versions[src] <= 22 && dst < SERVER_MAX_VERSIONS - 1) {\n                asp_versions[dst++] = versions[src];\n            }\n        }\n\n        server->using_version = pick_version(asp_versions, 0);\n    } else {\n        server->using_version = pick_version(versions, requested_version);\n    }\n\n    if (server->using_version == NULL) {\n        log_for_client(priv, AFPFSD, LOG_ERR,\n                       \"Server cannot handle AFP version %d\",\n                       requested_version);\n        errno = EPROTONOSUPPORT;\n        goto error;\n    }\n"""

    count = text.count(old)
    if count != 1:
        die("server.c guard expected once, found {}".format(count))

    text = text.replace(old, new, 1)

    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)

    print("ASP AFP auto-version cap ready: {}".format(root))


if __name__ == "__main__":
    main()
