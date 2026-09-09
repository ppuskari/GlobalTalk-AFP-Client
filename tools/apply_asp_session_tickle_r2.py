#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Correct client-originated ASP session maintenance for AFP-over-DDP.
#
# Netatalk Client's generic loop only sends periodic tickles to servers with a
# DSI/TCP fd.  Our ASP/DDP transport intentionally has no such fd, so a classic
# server can age out a busy session during long transfers.  In addition, the
# original ASP shim sent its tickle to the NBP listener socket and reused the
# AFP command sequence in bytes 2-3.
#
# R2 fixes both sides:
# - make connected ASP sessions eligible for the generic periodic tickle loop
# - mirror libatalk asp_tickle(): peer session endpoint, bytes 2-3 zero,
#   response_count=0, timeout=0, tries=1, flags=0
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK ASP SESSION TICKLE R2"
LOOP_MARKER = "GLOBALTALK ASP TICKLE LOOP R2"


def die(msg):
    raise SystemExit("apply_asp_session_tickle_r2: " + msg)


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


def patch_transport(path):
    text = read_text(path)

    if MARKER in text:
        return

    start, end = function_span(text, "int asp_transport_tickle(")

    replacement = r'''int asp_transport_tickle(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    struct atp_block atpb;
    struct sockaddr_at target;
    unsigned char request[ASP_HDRSIZ];

    if (!ctx || !ctx->session_open || !ctx->atp) {
        errno = ENOTCONN;
        return -1;
    }

    /* GLOBALTALK ASP SESSION TICKLE R2
     * Mirror libatalk asp_tickle(): tickle the server's session endpoint,
     * not its NBP/listener socket.  ASP tickles have zero user bytes 2-3,
     * request no ATP response, are not XO transactions, and are sent once. */
    memset(&atpb, 0, sizeof(atpb));
    request[0] = ASPFUNC_TICKLE;
    request[1] = ctx->sid;
    request[2] = 0;
    request[3] = 0;

    target = ctx->session;
    atpb.atp_saddr = &target;
    atpb.atp_sreqdata = (char *)request;
    atpb.atp_sreqdlen = sizeof(request);
    atpb.atp_sreqto = 0;
    atpb.atp_sreqtries = 1;

    if (atp_sreq(ctx->atp, &atpb, 0, 0) < 0) {
        return -1;
    }

    return 0;
}'''

    text = text[:start] + replacement + text[end:]
    write_text(path, text)


def patch_loop(path):
    text = read_text(path)

    if LOOP_MARKER in text:
        return

    old = '''                    if (s->connect_state == SERVER_STATE_CONNECTED && s->fd >= 0) {\n'''
    new = '''                    /* GLOBALTALK ASP TICKLE LOOP R2\n                     * ASP/DDP sessions deliberately have no DSI/TCP fd, but\n                     * still require the same periodic session tickle. */\n                    if (s->connect_state == SERVER_STATE_CONNECTED\n                            && (s->fd >= 0 || s->asp)) {\n'''

    count = text.count(old)
    if count != 1:
        die("loop tickle guard expected once, found {}".format(count))

    text = text.replace(old, new, 1)
    write_text(path, text)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_asp_session_tickle_r2.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    transport = os.path.join(root, "lib", "asp_transport.c")
    loop = os.path.join(root, "lib", "loop.c")

    if not os.path.isfile(transport):
        die("missing {}".format(transport))
    if not os.path.isfile(loop):
        die("missing {}".format(loop))

    patch_transport(transport)
    patch_loop(loop)

    print("Applied ASP session tickle R2: {}".format(root))
    print("  periodic loop includes fd-less ASP/DDP sessions")
    print("  destination: server session socket")
    print("  ATP: response_count=0 timeout=0 tries=1 flags=0")


if __name__ == "__main__":
    main()
