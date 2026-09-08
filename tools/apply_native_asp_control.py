#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# AFP servers may send ASP Attention transactions to the workstation session
# socket while an ordinary AFP command is still in flight. If the client only
# waits for ATP_TRESP, the server can block waiting for the attention ACK and
# never reach the command reply. Service those server-initiated ASP control
# requests while waiting for either ordinary replies or FPWrite/WriteContinue.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "asp_transport.c")
MARKER = "GLOBALTALK NATIVE ASP CONTROL R1"


def die(msg):
    raise SystemExit("apply_native_asp_control: " + msg)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


if not os.path.exists(PATH):
    die("missing {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("Native ASP control handling already applied: {}".format(UP))
    raise SystemExit(0)

anchor = '''/*
 * One ATP transaction.
 *
 * The first four bytes of each ATP request/response are ASP user bytes.
 * Response data after those four bytes is concatenated into payload.
 */
static int asp_xact(struct afpc_asp *ctx,
'''

helper = r'''/* GLOBALTALK NATIVE ASP CONTROL R1
 *
 * An AFP server may issue an ASP Attention to the workstation session socket
 * while it is processing a mutating AFP command. The server-side attention
 * path waits for an ATP response before returning. Therefore a client that
 * waits only for the original command TRESP can deadlock: the filesystem
 * mutation happens, the server waits for the Attention ACK, and the command
 * reply is never sent.
 *
 * Consume one already-selected incoming ATP request and handle the ASP control
 * functions that are valid asynchronously. WRTCONT is intentionally left to
 * the dedicated FPWrite transaction path.
 */
static int asp_service_control_request(struct afpc_asp *ctx,
                                       const struct sockaddr_at *peer)
{
    struct atp_block atpb;
    struct sockaddr_at from;
    struct iovec iov;
    unsigned char request[ATP_MAXDATA];
    unsigned char reply[ASP_HDRSIZ];
    unsigned int function;

    if (!ctx || !ctx->atp || !peer) {
        errno = EINVAL;
        return -1;
    }

    memset(&atpb, 0, sizeof(atpb));
    memset(&from, 0, sizeof(from));
    memset(request, 0, sizeof(request));
    memset(reply, 0, sizeof(reply));

    from = *peer;
    atpb.atp_saddr = &from;
    atpb.atp_rreqdata = (char *)request;
    atpb.atp_rreqdlen = sizeof(request);

    if (atp_rreq(ctx->atp, &atpb) < 0) {
        return -1;
    }

    if (atpb.atp_rreqdlen < ASP_HDRSIZ) {
        errno = EPROTO;
        return -1;
    }

    if (from.sat_addr.s_net != peer->sat_addr.s_net ||
            from.sat_addr.s_node != peer->sat_addr.s_node ||
            from.sat_port != peer->sat_port) {
        errno = EPROTO;
        return -1;
    }

    function = request[0];

    if (function == ASPFUNC_TICKLE) {
        /* Tickle is an ATP request with response_count == 0. */
        if (ctx->session_open && request[1] != ctx->sid) {
            errno = EPROTO;
            return -1;
        }
        return 0;
    }

    if (function == ASPFUNC_ATTN) {
        if (!ctx->session_open || request[1] != ctx->sid) {
            errno = EPROTO;
            return -1;
        }

        /* The ASP Attention sender waits for one ATP response packet and does
         * not interpret its four ASP user bytes. Return the conventional
         * all-zero acknowledgement. */
        iov.iov_base = reply;
        iov.iov_len = sizeof(reply);
        atpb.atp_sresiov = &iov;
        atpb.atp_sresiovcnt = 1;

        if (atp_sresp(ctx->atp, &atpb) < 0) {
            return -1;
        }

        log_for_client(NULL, AFPFSD, LOG_DEBUG,
                       "ASP attention acknowledged: flags %02x%02x",
                       (unsigned int)request[2],
                       (unsigned int)request[3]);
        return 0;
    }

    errno = EPROTO;
    log_for_client(NULL, AFPFSD, LOG_ERR,
                   "Unexpected server ASP request while waiting for reply: %u",
                   function);
    return -1;
}

'''

text = replace_once(text, anchor, helper + anchor,
                    "asp_xact helper anchor")

old = '''    atpb.atp_rresiov = iov;
    atpb.atp_rresiovcnt = (int)response_count;

    if (atp_rresp(ctx->atp, &atpb) < 0) {
        return -1;
    }

    for (i = 0; i < (unsigned int)atpb.atp_rresiovcnt; i++) {
'''

new = '''    /* GLOBALTALK NATIVE ASP CONTROL R1
     * Wait for either side of the session. A server Attention is a TREQ to
     * our workstation socket and must be acknowledged before some servers send
     * the original AFP command response.
     */
    for (;;) {
        struct sockaddr_at from = target;
        int rc = atp_rsel(ctx->atp, &from, 0);

        if (rc < 0) {
            return -1;
        }
        if (rc == 0) {
            continue;
        }
        if (rc == ATP_TREQ) {
            if (asp_service_control_request(ctx, &target) < 0) {
                return -1;
            }
            continue;
        }
        if (rc == ATP_TRESP) {
            break;
        }
    }

    atpb.atp_rresiov = iov;
    atpb.atp_rresiovcnt = (int)response_count;

    if (atp_rresp(ctx->atp, &atpb) < 0) {
        return -1;
    }

    for (i = 0; i < (unsigned int)atpb.atp_rresiovcnt; i++) {
'''

text = replace_once(text, old, new, "asp_xact response wait")

# The R2 WriteContinue helper receives a server TREQ itself. It originally
# assumed every such request was WRTCONT. Permit asynchronous Tickle/Attention
# there as well so a write transaction remains bidirectional and cannot be
# stalled by the same synchronous Attention handshake.
write_old = '''    if (atpb.atp_rreqdlen < 6 ||
            request[0] != ASPFUNC_WRTCONT ||
            request[1] != ctx->sid) {
        errno = EPROTO;
        return -1;
    }

    if (from.sat_addr.s_net != ctx->session.sat_addr.s_net ||
            from.sat_addr.s_node != ctx->session.sat_addr.s_node ||
            from.sat_port != ctx->session.sat_port) {
        errno = EPROTO;
        return -1;
    }

    memcpy(&seq, &request[2], sizeof(seq));
'''

write_new = '''    if (atpb.atp_rreqdlen < ASP_HDRSIZ ||
            request[1] != ctx->sid) {
        errno = EPROTO;
        return -1;
    }

    if (from.sat_addr.s_net != ctx->session.sat_addr.s_net ||
            from.sat_addr.s_node != ctx->session.sat_addr.s_node ||
            from.sat_port != ctx->session.sat_port) {
        errno = EPROTO;
        return -1;
    }

    if (request[0] == ASPFUNC_TICKLE) {
        return 0;
    }

    if (request[0] == ASPFUNC_ATTN) {
        memset(packets[0], 0, ASP_HDRSIZ);
        iov[0].iov_base = packets[0];
        iov[0].iov_len = ASP_HDRSIZ;
        atpb.atp_sresiov = iov;
        atpb.atp_sresiovcnt = 1;

        if (atp_sresp(ctx->atp, &atpb) < 0) {
            return -1;
        }

        log_for_client(NULL, AFPFSD, LOG_DEBUG,
                       "ASP attention acknowledged during write: flags %02x%02x",
                       (unsigned int)request[2],
                       (unsigned int)request[3]);
        return 0;
    }

    if (atpb.atp_rreqdlen < 6 ||
            request[0] != ASPFUNC_WRTCONT) {
        errno = EPROTO;
        return -1;
    }

    memcpy(&seq, &request[2], sizeof(seq));
'''

text = replace_once(text, write_old, write_new,
                    "WriteContinue control handling")

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied native ASP control handling: {}".format(UP))
