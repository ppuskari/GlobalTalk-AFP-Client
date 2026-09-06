#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Apply ASP resource-fork R2 transport fixes to an already bootstrapped
# Netatalk Client 0.9.5 work tree. Every edit is guarded and idempotent.

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
UP = (Path(sys.argv[1]).resolve()
      if len(sys.argv) > 1
      else ROOT / "work" / "netatalk-client")

MARKER = "GLOBALTALK ASP RFORK R2"


def die(msg):
    raise SystemExit("apply_rfork_r2: " + msg)


def replace_once(path, old, new):
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}: {!r}".format(
            path, count, old[:80]))
    path.write_text(text.replace(old, new, 1))


asp = UP / "lib" / "asp_transport.c"
low = UP / "lib" / "lowlevel.c"

if not asp.exists() or not low.exists():
    die("patched Netatalk Client tree not found: {}".format(UP))

text = asp.read_text()
if MARKER in text:
    print("ASP resource-fork R2 already applied: {}".format(UP))
    raise SystemExit(0)

# The AFP command itself is limited to one 578-byte ASP command packet, but
# FPWrite data is delivered separately by ASP WriteContinue and may use all
# eight ATP response packets: 8 * 578 = 4624 bytes.
replace_once(
    asp,
    "    server->tx_quantum = AFPC_ASP_COMMAND_DATA;\n",
    "    /* {}: WRTCONT can carry the full eight-packet ASP data quantum. */\n"
    "    server->tx_quantum = AFPC_ASP_MAX_DATA;\n".format(MARKER),
)

text = asp.read_text()
start = text.find("int asp_transport_send(struct afp_server *server,")
end = text.find("int asp_transport_tickle(struct afp_server *server)")
if start < 0 or end < 0 or end <= start:
    die("asp_transport.c: could not isolate asp_transport_send()")
if text.find("int asp_transport_send(struct afp_server *server,", start + 1) >= 0:
    die("asp_transport.c: asp_transport_send() marker is not unique")

replacement = r'''/* GLOBALTALK ASP RFORK R2
 *
 * FPWrite over ASP is a two-sided transaction. The client first submits an
 * ASPFUNC_WRITE containing only the AFP FPWrite parameter block. The AFP
 * server then sends ASPFUNC_WRTCONT back to the client's workstation session
 * socket and the client answers that ATP request with the actual fork bytes.
 * The final ATP response to ASPFUNC_WRITE contains the normal AFP result and
 * resulting fork offset.
 */
static int asp_reply_write_continue(struct afpc_asp *ctx,
                                    const unsigned char *data,
                                    size_t data_len,
                                    size_t *data_sent)
{
    struct atp_block atpb;
    struct sockaddr_at from;
    struct iovec iov[AFPC_ASP_MAX_PACKETS];
    unsigned char request[ATP_MAXDATA];
    unsigned char packets[AFPC_ASP_MAX_PACKETS][ASP_CMDMAXSIZ];
    uint16_t seq;
    uint16_t requested;
    size_t remaining;
    size_t send_len;
    size_t pos;
    unsigned int packet_count;
    unsigned int i;

    if (!ctx || !ctx->atp || !data_sent || *data_sent > data_len) {
        errno = EINVAL;
        return -1;
    }

    memset(&atpb, 0, sizeof(atpb));
    memset(&from, 0, sizeof(from));
    memset(request, 0, sizeof(request));
    memset(packets, 0, sizeof(packets));

    from.sat_family = AF_APPLETALK;
    from.sat_addr.s_net = ATADDR_ANYNET;
    from.sat_addr.s_node = ATADDR_ANYNODE;
    from.sat_port = ATADDR_ANYPORT;

    atpb.atp_saddr = &from;
    atpb.atp_rreqdata = (char *)request;
    atpb.atp_rreqdlen = sizeof(request);

    if (atp_rreq(ctx->atp, &atpb) < 0) {
        return -1;
    }

    if (atpb.atp_rreqdlen < 6 ||
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
    if (ntohs(seq) != ctx->sequence) {
        errno = EPROTO;
        return -1;
    }

    memcpy(&requested, &request[4], sizeof(requested));
    requested = ntohs(requested);

    remaining = data_len - *data_sent;
    send_len = requested;
    if (send_len > remaining) {
        send_len = remaining;
    }
    if (send_len > AFPC_ASP_MAX_DATA) {
        send_len = AFPC_ASP_MAX_DATA;
    }

    packet_count = (unsigned int)((send_len + AFPC_ASP_COMMAND_DATA - 1) /
                                  AFPC_ASP_COMMAND_DATA);
    if (packet_count == 0) {
        packet_count = 1;
    }
    if (packet_count > AFPC_ASP_MAX_PACKETS) {
        errno = EMSGSIZE;
        return -1;
    }

    pos = 0;
    for (i = 0; i < packet_count; i++) {
        size_t chunk = send_len - pos;
        if (chunk > AFPC_ASP_COMMAND_DATA) {
            chunk = AFPC_ASP_COMMAND_DATA;
        }

        /* Four ASP user bytes are present on every ATP response packet. */
        memset(packets[i], 0, ASP_HDRSIZ);
        if (chunk) {
            memcpy(packets[i] + ASP_HDRSIZ,
                   data + *data_sent + pos,
                   chunk);
        }

        iov[i].iov_base = packets[i];
        iov[i].iov_len = ASP_HDRSIZ + chunk;
        pos += chunk;
    }

    atpb.atp_sresiov = iov;
    atpb.atp_sresiovcnt = (int)packet_count;
    if (atp_sresp(ctx->atp, &atpb) < 0) {
        return -1;
    }

    *data_sent += send_len;
    return 0;
}

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
    struct atp_block atpb;
    struct sockaddr_at target;
    struct iovec iov[AFPC_ASP_MAX_PACKETS];
    unsigned char request[ASP_CMDMAXSIZ];
    unsigned char packets[AFPC_ASP_MAX_PACKETS][ASP_CMDMAXSIZ];
    uint16_t seq;
    size_t sent = 0;
    size_t total = 0;
    unsigned int i;
    int rc;

    if (!ctx || !ctx->atp || !afp_command ||
            afp_command_len == 0 ||
            afp_command_len > AFPC_ASP_COMMAND_DATA ||
            data_len > AFPC_ASP_MAX_DATA ||
            (data_len && !data)) {
        errno = EINVAL;
        return -1;
    }

    memset(&atpb, 0, sizeof(atpb));
    memset(request, 0, sizeof(request));
    memset(packets, 0, sizeof(packets));
    memset(response_headers, 0,
           AFPC_ASP_MAX_PACKETS * ASP_HDRSIZ);

    request[0] = ASPFUNC_WRITE;
    request[1] = ctx->sid;
    seq = htons(ctx->sequence);
    memcpy(&request[2], &seq, sizeof(seq));
    memcpy(&request[ASP_HDRSIZ], afp_command, afp_command_len);

    target = ctx->session;
    atpb.atp_saddr = &target;
    atpb.atp_sreqdata = (char *)request;
    atpb.atp_sreqdlen = (int)(ASP_HDRSIZ + afp_command_len);
    atpb.atp_sreqto = 2;
    atpb.atp_sreqtries = 5;

    if (atp_sreq(ctx->atp, &atpb,
                 AFPC_ASP_MAX_PACKETS, ATP_XO) < 0) {
        return -1;
    }

    for (;;) {
        struct sockaddr_at from = ctx->session;

        /* func == 0 means TREQ or TRESP. This is what lets us service the
         * server's WriteContinue request while our FPWrite ATP request is
         * still outstanding. */
        rc = atp_rsel(ctx->atp, &from, 0);
        if (rc < 0) {
            return -1;
        }
        if (rc == 0) {
            continue;
        }

        if (rc == ATP_TREQ) {
            if (asp_reply_write_continue(ctx, data, data_len, &sent) < 0) {
                return -1;
            }
            continue;
        }

        if (rc == ATP_TRESP) {
            break;
        }
    }

    for (i = 0; i < AFPC_ASP_MAX_PACKETS; i++) {
        iov[i].iov_base = packets[i];
        iov[i].iov_len = sizeof(packets[i]);
    }

    target = ctx->session;
    atpb.atp_saddr = &target;
    atpb.atp_rresiov = iov;
    atpb.atp_rresiovcnt = AFPC_ASP_MAX_PACKETS;

    if (atp_rresp(ctx->atp, &atpb) < 0) {
        return -1;
    }

    for (i = 0; i < (unsigned int)atpb.atp_rresiovcnt; i++) {
        size_t n = iov[i].iov_len;
        size_t body;

        if (n < ASP_HDRSIZ) {
            errno = EPROTO;
            return -1;
        }

        memcpy(response_headers[i], packets[i], ASP_HDRSIZ);
        body = n - ASP_HDRSIZ;
        if (body > payload_cap - total) {
            errno = EMSGSIZE;
            return -1;
        }
        if (body) {
            memcpy(payload + total,
                   packets[i] + ASP_HDRSIZ,
                   body);
            total += body;
        }
    }

    if (payload_len) {
        *payload_len = total;
    }
    return 0;
}

int asp_transport_send(struct afp_server *server,
                       const char *dsi_msg,
                       int dsi_size,
                       int wait,
                       unsigned char subcommand,
                       void *other)
{
    struct afpc_asp *ctx = ctx_of(server);
    const struct dsi_header *dsi;
    const unsigned char *afp;
    const unsigned char *write_data = NULL;
    size_t afp_len;
    size_t command_len;
    size_t write_len = 0;
    unsigned char request[ASP_CMDMAXSIZ];
    uint8_t headers[AFPC_ASP_MAX_PACKETS][4];
    unsigned char payload[AFPC_ASP_MAX_DATA];
    size_t payload_len = 0;
    uint16_t seq;
    uint32_t net_result;
    int32_t result;
    int parser_result;

    (void)wait;

    if (!ctx || !ctx->session_open ||
            !dsi_msg ||
            dsi_size < (int)sizeof(struct dsi_header)) {
        errno = ENOTCONN;
        return -1;
    }

    dsi = (const struct dsi_header *)dsi_msg;
    afp = (const unsigned char *)dsi_msg + sizeof(struct dsi_header);
    afp_len = (size_t)dsi_size - sizeof(struct dsi_header);
    command_len = afp_len;

    if (dsi->command == DSI_DSIWrite) {
        uint32_t data_offset = ntohl(dsi->return_code.data_offset);

        if (data_offset == 0 || data_offset > afp_len) {
            errno = EPROTO;
            return -1;
        }

        command_len = data_offset;
        write_data = afp + data_offset;
        write_len = afp_len - data_offset;

        if (command_len > AFPC_ASP_COMMAND_DATA ||
                write_len > AFPC_ASP_MAX_DATA) {
            errno = EMSGSIZE;
            return -1;
        }

        if (asp_write_xact(ctx,
                           afp, command_len,
                           write_data, write_len,
                           headers,
                           payload, sizeof(payload),
                           &payload_len) < 0) {
            return -1;
        }
    } else {
        if (afp_len > AFPC_ASP_COMMAND_DATA) {
            log_for_client(NULL, AFPFSD, LOG_ERR,
                           "ASP command request too large: %zu > %u",
                           afp_len, AFPC_ASP_COMMAND_DATA);
            errno = EMSGSIZE;
            return -1;
        }

        request[0] = ASPFUNC_CMD;
        request[1] = ctx->sid;
        seq = htons(ctx->sequence);
        memcpy(&request[2], &seq, sizeof(seq));
        memcpy(&request[ASP_HDRSIZ], afp, afp_len);

        if (asp_xact(ctx, &ctx->session,
                     request, ASP_HDRSIZ + afp_len,
                     AFPC_ASP_MAX_PACKETS,
                     headers,
                     payload, sizeof(payload),
                     &payload_len) < 0) {
            return -1;
        }
    }

    memcpy(&net_result, headers[0], sizeof(net_result));
    result = (int32_t)ntohl(net_result);

    /* Server advances ASP sequence after every command/write reply. */
    ctx->sequence++;

    if (synthesize_dsi_reply(server, dsi,
                             dsi->command,
                             result,
                             payload, payload_len) < 0) {
        return -1;
    }

    server->stats.tx_bytes += ASP_HDRSIZ + afp_len;

    /* Do not call dsi_command_reply(); ASP has already assembled the reply. */
    parser_result = afp_reply(subcommand, server, other);

    if (parser_result < 0) {
        log_for_client(NULL, AFPFSD, LOG_ERR,
                       "ASP AFP reply parser failed: command %u, payload %zu bytes, result %d",
                       (unsigned int)subcommand, payload_len, (int)result);
    }

    if (result != 0) {
        return result;
    }

    return parser_result;
}

'''

asp.write_text(text[:start] + replacement + text[end:])

# Netatalk Client 0.9.5 incorrectly treats a short successful read as EOF.
# Classic AFP/ASP servers can legally return kFPNoErr with less than the
# requested count (the ASP command-reply ceiling is 4624 bytes). Continue
# from the returned offset; only kFPEOFErr establishes EOF.
old = """        totalsize += buffer.size;\n\n        if ((size_t)buffer.size < chunksize) {\n            *eof = 1;\n            break;\n        }\n"""
new = """        /* GLOBALTALK ASP RFORK R2: a short kFPNoErr read is not EOF.\n         * Continue from the returned offset; only explicit kFPEOFErr above\n         * establishes EOF. */\n        totalsize += buffer.size;\n"""
replace_once(low, old, new)

print("Applied ASP resource-fork R2 transport fixes to: {}".format(UP))
