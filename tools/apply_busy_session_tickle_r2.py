#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Keep ASP sessions alive during continuously busy AFP-over-DDP transfers.
#
# Netatalk Client's generic 30-second tickle is driven by an idle pselect()
# timeout.  A sustained stateless archive transfer continuously wakes that
# loop, so the timeout may never fire.  The session can therefore expire even
# though AFP commands are flowing continuously.
#
# This patch adds a second, transaction-path scheduler.  While holding the
# ASP/native-ATP serialization mutex, each command/write checks elapsed time
# since the last client tickle.  If 30 seconds have elapsed it emits the same
# no-response ASP session tickle before starting the next AFP transaction.
# The generic idle tickle remains in place and updates the same timestamp.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK BUSY SESSION TICKLE R2B"


def die(msg):
    raise SystemExit("apply_busy_session_tickle_r2: " + msg)


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


def patch_wrapper(text, signature, call_anchor, what):
    start, end = function_span(text, signature)
    body = text[start:end]

    guarded = "asp_maybe_busy_tickle_unlocked(ctx)"
    if guarded in body:
        return text

    new_call = (
        "    if (asp_maybe_busy_tickle_unlocked(ctx) < 0) {\n"
        "        pthread_mutex_unlock(&ctx->io_lock);\n"
        "        return -1;\n"
        "    }\n\n" + call_anchor
    )

    if body.count(call_anchor) != 1:
        die("{} call anchor expected once, found {}".format(
            what, body.count(call_anchor)))

    body = body.replace(call_anchor, new_call, 1)
    return text[:start] + body + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_busy_session_tickle_r2.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "lib", "asp_transport.c")

    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)

    if MARKER in text:
        print("Busy-session tickle R2B already applied: {}".format(path))
        return

    if "GLOBALTALK ASP IO SERIALIZATION R2" not in text:
        die("ASP serialization R2 must be applied first")
    if "GLOBALTALK ASP SESSION TICKLE R2" not in text:
        die("ASP session tickle R2 must be applied first")

    text = replace_once(
        text,
        "#include <sys/uio.h>\n",
        "#include <sys/uio.h>\n#include <time.h>\n",
        "time include")

    text = replace_once(
        text,
        "    pthread_mutex_t io_lock;\n"
        "    int io_lock_ready;\n"
        "    char object[NBPSTRLEN + 1];\n",
        "    pthread_mutex_t io_lock;\n"
        "    int io_lock_ready;\n"
        "    time_t last_client_tickle;\n"
        "    char object[NBPSTRLEN + 1];\n",
        "tickle timestamp field")

    helper_anchor = "static int asp_xact_unlocked("
    if text.count(helper_anchor) != 1:
        die("asp_xact_unlocked anchor missing/non-unique")

    helper = r'''/* GLOBALTALK BUSY SESSION TICKLE R2B
 *
 * A continuously busy stateless client can prevent Netatalk Client's generic
 * pselect timeout from ever expiring.  Keep the ASP session's workstation
 * tickle cadence independent of daemon idleness by checking it while the
 * native ATP transaction lock is already held.
 */
static int asp_send_client_tickle_unlocked(struct afpc_asp *ctx)
{
    struct atp_block atpb;
    struct sockaddr_at target;
    unsigned char request[ASP_HDRSIZ];
    time_t now;

    if (!ctx || !ctx->session_open || !ctx->atp) {
        return 0;
    }

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

    now = time(NULL);
    if (now != (time_t)-1) {
        ctx->last_client_tickle = now;
    }
    return 0;
}

static int asp_maybe_busy_tickle_unlocked(struct afpc_asp *ctx)
{
    time_t now;

    if (!ctx || !ctx->session_open || !ctx->atp) {
        return 0;
    }

    now = time(NULL);
    if (now != (time_t)-1 && ctx->last_client_tickle != 0
            && now >= ctx->last_client_tickle
            && now - ctx->last_client_tickle < 30) {
        return 0;
    }

    return asp_send_client_tickle_unlocked(ctx);
}

'''

    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    text = replace_once(
        text,
        "    ctx->session_open = 1;\n\n"
        "    log_for_client(NULL, AFPFSD, LOG_NOTICE,\n",
        "    ctx->session_open = 1;\n"
        "    ctx->last_client_tickle = time(NULL);\n\n"
        "    log_for_client(NULL, AFPFSD, LOG_NOTICE,\n",
        "OpenSession tickle timestamp")

    text = patch_wrapper(
        text,
        "static int asp_xact(struct afpc_asp *ctx,",
        "    ret = asp_xact_unlocked(ctx, dest, request, request_len,\n",
        "asp_xact")

    text = patch_wrapper(
        text,
        "static int asp_write_xact(struct afpc_asp *ctx,",
        "    ret = asp_write_xact_unlocked(ctx, afp_command, afp_command_len,\n",
        "asp_write_xact")

    tickle_start, tickle_end = function_span(text, "int asp_transport_tickle(")
    tickle = text[tickle_start:tickle_end]
    old = """    if (ret < 0) {\n        return -1;\n    }\n\n    return 0;\n"""
    new = """    if (ret < 0) {\n        return -1;\n    }\n\n    {\n        time_t now = time(NULL);\n        if (now != (time_t)-1) {\n            ctx->last_client_tickle = now;\n        }\n    }\n\n    return 0;\n"""
    if tickle.count(old) != 1:
        die("asp_transport_tickle success anchor missing/non-unique")
    tickle = tickle.replace(old, new, 1)
    text = text[:tickle_start] + tickle + text[tickle_end:]

    text = replace_once(
        text,
        "    ctx->session_open = 0;\n"
        "    ctx->sid = 0;\n"
        "    ctx->sequence = 0;\n",
        "    ctx->session_open = 0;\n"
        "    ctx->sid = 0;\n"
        "    ctx->sequence = 0;\n"
        "    ctx->last_client_tickle = 0;\n",
        "close-session tickle reset")

    write_text(path, text)

    print("Applied busy-session tickle R2B: {}".format(path))
    print("  active AFP traffic now drives the 30-second ASP tickle cadence")
    print("  idle-loop tickles remain enabled")
    print("  all tickles share the native ATP serialization lock")


if __name__ == "__main__":
    main()
