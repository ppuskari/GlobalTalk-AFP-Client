#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Netatalk Client 0.9.5 assumes a successful FPCreateDir reply always
# contains four bytes after the DSI header.  Some classic AFP-over-ASP
# servers perform the create successfully but return only the AFP result.
# Accept both forms.  When a 32-bit directory ID is present, decode it.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "proto_directory.c")
MARKER = "GLOBALTALK FPCreateDir REPLY COMPAT"


def die(msg):
    raise SystemExit("apply_createdir_reply_compat: " + msg)


if not os.path.exists(PATH):
    die("missing {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("FPCreateDir reply compatibility already applied: {}".format(UP))
    raise SystemExit(0)

old = '''int afp_createdir_reply(struct afp_server *server _U_,
                        char *buf, unsigned int size, void *other)
{
    /* We're actually just going to ignore the return bitmap and forkid. */
    struct {
        struct dsi_header header __attribute__((__packed__));
        uint16_t bitmap;
        uint16_t forkid;
    } __attribute__((__packed__)) * reply_packet = (void *) buf;
    unsigned short *dir_p = (void *) other;
    *dir_p = 0;

    if (reply_packet->header.return_code.error_code) {
        return (reply_packet->header.return_code.error_code);
    }

    if (size < sizeof(*reply_packet)) {
        return -1;
    }

    return 0;
}
'''

new = '''int afp_createdir_reply(struct afp_server *server _U_,
                        char *buf, unsigned int size, void *other)
{
    /* GLOBALTALK FPCreateDir REPLY COMPAT
     *
     * A successful FPCreateDir reply may be either:
     *   - result only (classic servers seen over ASP), or
     *   - result plus a 32-bit directory ID.
     *
     * The caller only requires success here, but preserve the returned DID
     * when the server supplies it.  Do not reinterpret the payload as the
     * bitmap/forkid layout used by FPOpenFork.
     */
    struct dsi_header *header = (void *)buf;
    unsigned int *dir_p = (void *)other;
    uint32_t net_did;
    unsigned int payload_size;

    if (size < sizeof(*header)) {
        return -1;
    }

    if (header->return_code.error_code) {
        return header->return_code.error_code;
    }

    if (dir_p) {
        *dir_p = 0;
    }

    payload_size = size - sizeof(*header);
    if (payload_size == 0) {
        return 0;
    }

    if (payload_size < sizeof(net_did)) {
        return -1;
    }

    memcpy(&net_did, buf + sizeof(*header), sizeof(net_did));
    if (dir_p) {
        *dir_p = ntohl(net_did);
    }

    return 0;
}
'''

count = text.count(old)
if count != 1:
    die("expected afp_createdir_reply guard once, found {}".format(count))

text = text.replace(old, new, 1)
with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied FPCreateDir reply compatibility: {}".format(UP))
