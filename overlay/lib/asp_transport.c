/*
 * GlobalTalk AFP Client -- AFP-over-DDP/ASP transport
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * Netatalk Client 0.9.5 supplies AFP request serialization, login,
 * volume/file logic and reply parsers.
 *
 * Netatalk 4.5.x libatalk supplies NBP and ATP over Linux AF_APPLETALK.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/uio.h>

#include <netatalk/at.h>
#include <atalk/atp.h>
#include <atalk/asp.h>
#include <atalk/nbp.h>

#include "afp.h"
#include "afp_internal.h"
#include "afp_replies.h"
#include "asp_transport.h"
#include "compat.h"
#include "dsi.h"
#include "dsi_protocol.h"
#include "libafpclient.h"
#include "uams_def.h"
#include "utils.h"

struct afpc_asp {
    ATP atp;
    struct sockaddr_at listener;
    struct sockaddr_at session;
    uint8_t sid;
    uint16_t sequence;
    int session_open;
    char object[NBPSTRLEN + 1];
    char zone[NBPSTRLEN + 1];
};

static struct afpc_asp *ctx_of(struct afp_server *server)
{
    return (struct afpc_asp *)server->asp;
}

/*
 * One ATP transaction.
 *
 * The first four bytes of each ATP request/response are ASP user bytes.
 * Response data after those four bytes is concatenated into payload.
 */
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
    struct atp_block atpb;
    struct sockaddr_at target;
    struct iovec iov[AFPC_ASP_MAX_PACKETS];
    unsigned char packets[AFPC_ASP_MAX_PACKETS][ASP_CMDMAXSIZ];
    unsigned int i;
    size_t total = 0;

    if (!ctx || !ctx->atp || !dest || !request ||
            request_len < ASP_HDRSIZ ||
            request_len > ATP_MAXDATA ||
            response_count > AFPC_ASP_MAX_PACKETS) {
        errno = EINVAL;
        return -1;
    }

    memset(&atpb, 0, sizeof(atpb));
    memset(packets, 0, sizeof(packets));
    memset(response_headers, 0,
           AFPC_ASP_MAX_PACKETS * ASP_HDRSIZ);

    target = *dest;
    atpb.atp_saddr = &target;
    atpb.atp_sreqdata = (char *)request;
    atpb.atp_sreqdlen = (int)request_len;
    atpb.atp_sreqto = 2;
    atpb.atp_sreqtries = 5;

    if (atp_sreq(ctx->atp, &atpb,
                 (int)response_count, ATP_XO) < 0) {
        return -1;
    }

    if (response_count == 0) {
        if (payload_len) {
            *payload_len = 0;
        }
        return 0;
    }

    for (i = 0; i < response_count; i++) {
        iov[i].iov_base = packets[i];
        iov[i].iov_len = sizeof(packets[i]);
    }

    atpb.atp_rresiov = iov;
    atpb.atp_rresiovcnt = (int)response_count;

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

        memcpy(response_headers[i],
               packets[i], ASP_HDRSIZ);
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

static int synthesize_dsi_reply(struct afp_server *server,
                                const struct dsi_header *request_header,
                                unsigned char command,
                                int32_t result,
                                const unsigned char *payload,
                                size_t payload_len)
{
    struct dsi_header reply;
    size_t need = sizeof(reply) + payload_len;

    if (need > (size_t)server->bufsize) {
        char *p = realloc(server->incoming_buffer, need);
        if (!p) {
            return -1;
        }
        server->incoming_buffer = p;
        server->bufsize = (int)need;
    }

    memset(&reply, 0, sizeof(reply));
    reply.flags = DSI_REPLY;
    reply.command = command;
    if (request_header) {
        reply.requestid = request_header->requestid;
    }
    reply.return_code.error_code = htonl(result);
    reply.length = htonl((uint32_t)payload_len);

    memcpy(server->incoming_buffer, &reply, sizeof(reply));

    if (payload_len) {
        memcpy(server->incoming_buffer + sizeof(reply),
               payload, payload_len);
    }

    server->data_read = (int)need;
    server->stats.rx_bytes += need;
    return 0;
}

int asp_transport_configure(struct afp_server *server,
                            const char *object,
                            const char *zone)
{
    struct afpc_asp *ctx;

    if (!server || !object || !*object) {
        errno = EINVAL;
        return -1;
    }

    if (server->asp) {
        asp_transport_destroy(server);
    }

    ctx = calloc(1, sizeof(*ctx));
    if (!ctx) {
        return -1;
    }

    strlcpy(ctx->object, object, sizeof(ctx->object));
    strlcpy(ctx->zone,
            (zone && *zone) ? zone : "*",
            sizeof(ctx->zone));

    server->asp = ctx;
    server->tx_quantum = AFPC_ASP_COMMAND_DATA;
    server->rx_quantum = AFPC_ASP_MAX_DATA;
    return 0;
}

static int asp_resolve(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    struct nbpnve result;
    int n;

    if (!ctx) {
        errno = EINVAL;
        return -1;
    }

    memset(&result, 0, sizeof(result));

    n = nbp_lookup(ctx->object, "AFPServer",
                   ctx->zone, &result, 1, NULL);

    if (n <= 0) {
        if (errno == 0) {
            errno = ENOENT;
        }
        return -1;
    }

    ctx->listener = result.nn_sat;

    log_for_client(NULL, AFPFSD, LOG_NOTICE,
                   "DDP NBP resolved %s:AFPServer@%s to %u.%u:%u",
                   ctx->object, ctx->zone,
                   (unsigned int)ntohs(ctx->listener.sat_addr.s_net),
                   (unsigned int)ctx->listener.sat_addr.s_node,
                   (unsigned int)ctx->listener.sat_port);
    return 0;
}

static int asp_get_status(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    unsigned char request[ASP_HDRSIZ] = {
        ASPFUNC_STAT, 0, 0, 0
    };
    uint8_t headers[AFPC_ASP_MAX_PACKETS][4];
    unsigned char payload[AFPC_ASP_MAX_DATA];
    size_t payload_len = 0;

    if (!ctx) {
        errno = EINVAL;
        return -1;
    }

    if (!ctx->atp) {
        ctx->atp = atp_open(ATADDR_ANYPORT, NULL);
        if (!ctx->atp) {
            return -1;
        }
    }

    if (asp_xact(ctx, &ctx->listener,
                 request, sizeof(request),
                 AFPC_ASP_MAX_PACKETS,
                 headers,
                 payload, sizeof(payload),
                 &payload_len) < 0) {
        return -1;
    }

    if (synthesize_dsi_reply(server, NULL,
                             DSI_DSIGetStatus, 0,
                             payload, payload_len) < 0) {
        return -1;
    }

    /*
     * ASP GetStatus contains the same AFP server-status structure parsed
     * by Netatalk Client's DSI GetStatus reply decoder.
     */
    dsi_getstatus_reply(server);
    return 0;
}

int asp_transport_connect(struct afp_server *server,
                          int full_status)
{
    struct afpc_asp *ctx = ctx_of(server);

    if (!ctx) {
        errno = EINVAL;
        return -1;
    }

    asp_transport_close_session(server);

    if (asp_resolve(server) < 0) {
        return -1;
    }

    if (!ctx->atp) {
        ctx->atp = atp_open(ATADDR_ANYPORT, NULL);
        if (!ctx->atp) {
            return -1;
        }
    }

    server->connect_state = SERVER_STATE_CONNECTING;
    server->tx_quantum = AFPC_ASP_COMMAND_DATA;
    server->rx_quantum = AFPC_ASP_MAX_DATA;

    if (full_status && asp_get_status(server) < 0) {
        return -1;
    }

    return 0;
}

int asp_transport_open_session(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    unsigned char request[ASP_HDRSIZ];
    uint8_t headers[AFPC_ASP_MAX_PACKETS][4];
    unsigned char payload[AFPC_ASP_MAX_DATA];
    size_t payload_len = 0;
    uint16_t asp_error = 0;

    if (!ctx) {
        errno = EINVAL;
        return -1;
    }

    if (ctx->session_open) {
        return 0;
    }

    if (!ctx->atp) {
        ctx->atp = atp_open(ATADDR_ANYPORT, NULL);
        if (!ctx->atp) {
            return -1;
        }
    }

    request[0] = ASPFUNC_OPEN;
    request[1] = atp_sockaddr(ctx->atp)->sat_port;
    request[2] = 0;
    request[3] = 0;

    if (asp_xact(ctx, &ctx->listener,
                 request, sizeof(request), 1,
                 headers,
                 payload, sizeof(payload),
                 &payload_len) < 0) {
        return -1;
    }

    memcpy(&asp_error, &headers[0][2],
           sizeof(asp_error));

    if (asp_error != ASPERR_OK) {
        log_for_client(NULL, AFPFSD, LOG_ERR,
                       "ASP OpenSession failed: 0x%04x",
                       (unsigned int)asp_error);
        errno = ECONNREFUSED;
        return -1;
    }

    ctx->session = ctx->listener;
    ctx->session.sat_port = headers[0][0];
    ctx->sid = headers[0][1];
    ctx->sequence = 0;
    ctx->session_open = 1;

    log_for_client(NULL, AFPFSD, LOG_NOTICE,
                   "ASP session open: server socket %u, SID %u",
                   (unsigned int)ctx->session.sat_port,
                   (unsigned int)ctx->sid);

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
    size_t afp_len;
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
    afp = (const unsigned char *)dsi_msg +
          sizeof(struct dsi_header);
    afp_len = (size_t)dsi_size -
              sizeof(struct dsi_header);

    /*
     * Archive/pull path: all request-side commands are small.
     * Large outbound writes need ASP Write/WriteContinue and are Phase 2.
     */
    if (afp_len > AFPC_ASP_COMMAND_DATA) {
        log_for_client(NULL, AFPFSD, LOG_ERR,
                       "ASP Phase 1 request too large: %zu > %u",
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

    memcpy(&net_result, headers[0],
           sizeof(net_result));
    result = (int32_t)ntohl(net_result);

    /* Server advances ASP sequence after returning every command reply. */
    ctx->sequence++;

    if (synthesize_dsi_reply(server, dsi,
                             DSI_DSICommand,
                             result,
                             payload, payload_len) < 0) {
        return -1;
    }

    server->stats.tx_bytes += ASP_HDRSIZ + afp_len;

    /*
     * Do NOT call dsi_command_reply(): its afpRead special case performs
     * read(server->fd). ASP has already assembled the entire reply above.
     */
    parser_result = afp_reply(subcommand, server, other);

    if (result != 0) {
        return result;
    }

    return parser_result;
}

int asp_transport_tickle(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);
    unsigned char request[ASP_HDRSIZ];
    uint8_t headers[AFPC_ASP_MAX_PACKETS][4];
    unsigned char payload[1];
    size_t payload_len = 0;
    uint16_t seq;

    if (!ctx || !ctx->session_open) {
        errno = ENOTCONN;
        return -1;
    }

    request[0] = ASPFUNC_TICKLE;
    request[1] = ctx->sid;
    seq = htons(ctx->sequence);
    memcpy(&request[2], &seq, sizeof(seq));

    /*
     * Netatalk's ASP listener consumes tickles without a response,
     * hence ATP response_count=0.
     */
    return asp_xact(ctx, &ctx->listener,
                    request, sizeof(request), 0,
                    headers,
                    payload, sizeof(payload),
                    &payload_len);
}

void asp_transport_close_session(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);

    if (!ctx) {
        return;
    }

    if (ctx->session_open && ctx->atp) {
        unsigned char request[ASP_HDRSIZ];
        uint8_t headers[AFPC_ASP_MAX_PACKETS][4];
        unsigned char payload[1];
        size_t payload_len = 0;
        uint16_t seq;

        request[0] = ASPFUNC_CLOSE;
        request[1] = ctx->sid;
        seq = htons(ctx->sequence);
        memcpy(&request[2], &seq, sizeof(seq));

        (void)asp_xact(ctx, &ctx->session,
                       request, sizeof(request), 1,
                       headers,
                       payload, sizeof(payload),
                       &payload_len);
    }

    ctx->session_open = 0;
    ctx->sid = 0;
    ctx->sequence = 0;
}

void asp_transport_destroy(struct afp_server *server)
{
    struct afpc_asp *ctx = ctx_of(server);

    if (!ctx) {
        return;
    }

    asp_transport_close_session(server);

    if (ctx->atp) {
        atp_close(ctx->atp);
        ctx->atp = NULL;
    }

    free(ctx);
    server->asp = NULL;
}

struct afp_server *
asp_transport_full_connect(void *priv,
                           struct afp_connection_request *req)
{
    struct afp_server *server;
    unsigned int uams;

    server = afp_server_init(NULL);
    if (!server) {
        return NULL;
    }

    if (asp_transport_configure(server,
                                req->url.servername,
                                req->url.zone) < 0) {
        afp_free_server(&server);
        return NULL;
    }

    /*
     * afp_server_connect() is patched to dispatch server->asp here.
     * full=1 performs NBP + ASP GetStatus and adds the server to the
     * normal Netatalk Client server list.
     */
    if (afp_server_connect(server, 1) < 0) {
        asp_transport_destroy(server);
        afp_free_server(&server);
        return NULL;
    }

    uams = server->supported_uams;

    if (((req->url.username[0] == '\0' &&
          req->url.password[0] == '\0') ||
         strcmp(req->url.username, "nobody") == 0) &&
        (uams & UAM_NOUSERAUTHENT)) {
        req->uam_mask = UAM_NOUSERAUTHENT;
    }

    if (!afp_server_complete_connection(
            priv, server,
            server->versions,
            uams,
            req->url.username,
            req->url.password,
            req->url.requested_version,
            req->uam_mask)) {
        return NULL;
    }

    afp_server_identify(server);
    return server;
}
