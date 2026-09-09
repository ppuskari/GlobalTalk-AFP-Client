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
# R2 fixes all three pieces:
# - make connected ASP sessions eligible for the generic 30-second tickle loop
# - mirror libatalk asp_tickle(): peer session endpoint, bytes 2-3 zero,
#   response_count=0, timeout=0, tries=1, flags=0
# - serialize ASP command/write transactions and tickles around the native ATP
#   handle; the daemon executes commands on worker threads while its main loop
#   sends tickles, and native ATP deliberately supports one outgoing transaction
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK ASP SESSION TICKLE R2"
LOOP_MARKER = "GLOBALTALK ASP TICKLE LOOP R2"
LOCK_MARKER = "GLOBALTALK ASP IO SERIALIZATION R2"


def die(msg):
    raise SystemExit("apply_asp_session_tickle_r2: " + msg)


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


def add_io_lock(text):
    if LOCK_MARKER in text:
        return text

    text = replace_once(
        text,
        "#include <stdint.h>\n#include <stdlib.h>\n",
        "#include <stdint.h>\n#include <pthread.h>\n#include <stdlib.h>\n",
        "pthread include")

    text = replace_once(
        text,
        "    uint16_t sequence;\n    int session_open;\n    char object[NBPSTRLEN + 1];\n",
        "    uint16_t sequence;\n    int session_open;\n"
        "    /* GLOBALTALK ASP IO SERIALIZATION R2 */\n"
        "    pthread_mutex_t io_lock;\n"
        "    int io_lock_ready;\n"
        "    char object[NBPSTRLEN + 1];\n",
        "ASP context lock fields")

    text = replace_once(
        text,
        "    ctx = calloc(1, sizeof(*ctx));\n"
        "    if (!ctx) {\n"
        "        return -1;\n"
        "    }\n\n"
        "    strlcpy(ctx->object, object, sizeof(ctx->object));\n",
        "    ctx = calloc(1, sizeof(*ctx));\n"
        "    if (!ctx) {\n"
        "        return -1;\n"
        "    }\n\n"
        "    {\n"
        "        int lock_error = pthread_mutex_init(&ctx->io_lock, NULL);\n"
        "        if (lock_error != 0) {\n"
        "            free(ctx);\n"
        "            errno = lock_error;\n"
        "            return -1;\n"
        "        }\n"
        "        ctx->io_lock_ready = 1;\n"
        "    }\n\n"
        "    strlcpy(ctx->object, object, sizeof(ctx->object));\n",
        "ASP context lock initialization")

    text = replace_once(
        text,
        "    free(ctx);\n    server->asp = NULL;\n",
        "    if (ctx->io_lock_ready) {\n"
        "        pthread_mutex_destroy(&ctx->io_lock);\n"
        "        ctx->io_lock_ready = 0;\n"
        "    }\n\n"
        "    free(ctx);\n"
        "    server->asp = NULL;\n",
        "ASP context lock destruction")

    return text


def wrap_asp_xact(text):
    if "static int asp_xact_unlocked(" in text:
        return text

    start, end = function_span(text, "static int asp_xact(")
    original = text[start:end]
    unlocked = original.replace("static int asp_xact(",
                                "static int asp_xact_unlocked(", 1)

    wrapper = r'''

/* GLOBALTALK ASP IO SERIALIZATION R2
 * Native ATP intentionally owns one outgoing transaction.  Serialize the
 * daemon worker's AFP transaction against the main-loop ASP tickle. */
static int asp_xact(struct afpc_asp *ctx,
                    const struct sockaddr_at *dest,
                    const void *request,
                    size_t request_len,
                    unsigned int response_count,
                    uint8_t response_headers[AFPC_ASP_MAX_PACKETS][4],
                    unsigned char *payload,
                    size_t payload_cap,
                    size_t *payload_len)
{
    int lock_error;
    int ret;

    if (!ctx || !ctx->io_lock_ready) {
        errno = EINVAL;
        return -1;
    }

    lock_error = pthread_mutex_lock(&ctx->io_lock);
    if (lock_error != 0) {
        errno = lock_error;
        return -1;
    }

    ret = asp_xact_unlocked(ctx, dest, request, request_len,
                            response_count, response_headers,
                            payload, payload_cap, payload_len);
    pthread_mutex_unlock(&ctx->io_lock);
    return ret;
}
'''

    return text[:start] + unlocked + wrapper + text[end:]


def wrap_asp_write_xact(text):
    if "static int asp_write_xact_unlocked(" in text:
        return text

    signature = "static int asp_write_xact("
    if signature not in text:
        die("R2 write transaction helper not found")

    start, end = function_span(text, signature)
    original = text[start:end]
    unlocked = original.replace("static int asp_write_xact(",
                                "static int asp_write_xact_unlocked(", 1)

    wrapper = r'''

/* GLOBALTALK ASP IO SERIALIZATION R2 */
static int asp_write_xact(struct afpc_asp *ctx,
                          const unsigned char *afp_command,
                          size_t afp_command_len,
                          const unsigned char *data,
                          size_t data_len,
                          uint8_t response_headers[AFPC_ASP_MAX_PACKETS][4],
                          unsigned char *payload,
                          size_t payload_cap,
                          size_t *payload_len)
{
    int lock_error;
    int ret;

    if (!ctx || !ctx->io_lock_ready) {
        errno = EINVAL;
        return -1;
    }

    lock_error = pthread_mutex_lock(&ctx->io_lock);
    if (lock_error != 0) {
        errno = lock_error;
        return -1;
    }

    ret = asp_write_xact_unlocked(ctx, afp_command, afp_command_len,
                                  data, data_len, response_headers,
                                  payload, payload_cap, payload_len);
    pthread_mutex_unlock(&ctx->io_lock);
    return ret;
}
'''

    return text[:start] + unlocked + wrapper + text[end:]


def patch_tickle(text):
    if MARKER in text:
        return text

    start, end = function_span(text, "int asp_transport_tickle(")

    replacement = r'''int asp_transport_tickle(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    struct atp_block atpb;
    struct sockaddr_at target;
    unsigned char request[ASP_HDRSIZ];
    int lock_error;
    int ret;

    if (!ctx || !ctx->session_open || !ctx->atp || !ctx->io_lock_ready) {
        errno = ENOTCONN;
        return -1;
    }

    /* Do not block the daemon main loop behind a worker transaction.  A busy
     * session is already demonstrating liveness; the next 30-second tickle
     * cycle can try again.  The mutex also removes the race with native ATP's
     * single pending transaction state. */
    lock_error = pthread_mutex_trylock(&ctx->io_lock);
    if (lock_error == EBUSY) {
        return 0;
    }
    if (lock_error != 0) {
        errno = lock_error;
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

    ret = atp_sreq(ctx->atp, &atpb, 0, 0);
    pthread_mutex_unlock(&ctx->io_lock);

    if (ret < 0) {
        return -1;
    }

    return 0;
}'''

    return text[:start] + replacement + text[end:]


def patch_transport(path):
    text = read_text(path)
    text = add_io_lock(text)
    text = wrap_asp_xact(text)
    text = wrap_asp_write_xact(text)
    text = patch_tickle(text)
    write_text(path, text)


def patch_loop(path):
    text = read_text(path)

    if LOOP_MARKER in text:
        return

    old = '''                    if (s->connect_state == SERVER_STATE_CONNECTED && s->fd >= 0) {\n'''
    new = '''                    /* GLOBALTALK ASP TICKLE LOOP R2
                     * ASP/DDP sessions deliberately have no DSI/TCP fd, but
                     * still require the same periodic session tickle. */
                    if (s->connect_state == SERVER_STATE_CONNECTED
                            && (s->fd >= 0 || s->asp)) {
'''

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
    print("  ASP command/write/tickle access serialized")


if __name__ == "__main__":
    main()
