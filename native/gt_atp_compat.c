/*
 * GlobalTalk native ATP compatibility layer
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * This implements the libatalk ATP API subset used by the AFP-over-ASP
 * client, but keeps one explicit outgoing transaction and an explicit queue
 * for interleaved incoming requests.  Linux still supplies DDP through
 * AF_APPLETALK; only ATP transaction state is replaced here.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <netatalk/at.h>
#include <atalk/atp.h>
#include <atalk/ddp.h>
#include <atalk/netddp.h>

const char gt_native_atp_build_id[] =
    "GLOBALTALK NATIVE ATP R1";

#define GT_QUEUE_MAX 8

struct gt_packet {
    int valid;
    size_t len;
    struct sockaddr_at from;
    unsigned char data[ATP_BUFSIZ];
};

struct gt_xo_cache {
    int valid;
    struct sockaddr_at peer;
    uint16_t tid;
    int count;
    struct gt_packet packet[ATP_MAXRESP];
};

struct gt_atp_handle {
    struct atp_handle pub;

    int pending;
    struct sockaddr_at pending_peer;
    uint16_t pending_tid;
    uint8_t pending_ctrl;
    uint8_t pending_bitmap;
    int pending_respcount;
    int timeout_sec;
    int retries_left;
    int release_sent;
    size_t request_len;
    unsigned char request[ATP_BUFSIZ];
    struct gt_packet responses[ATP_MAXRESP];

    struct gt_packet queue[GT_QUEUE_MAX];
    unsigned int queue_head;
    unsigned int queue_count;

    int last_request_valid;
    struct sockaddr_at last_request_peer;
    uint16_t last_request_tid;
    uint8_t last_request_ctrl;
    uint8_t last_request_bitmap;

    struct gt_xo_cache xo;

    unsigned long tx_treq;
    unsigned long tx_tresp;
    unsigned long tx_trel;
    unsigned long rx_treq;
    unsigned long rx_tresp;
    unsigned long rx_trel;
    unsigned long retransmits;
    unsigned long timeouts;
    unsigned long duplicates;
    unsigned long wrong_tid;
    unsigned long wrong_peer;
    unsigned long bad_seq;
};

static struct gt_atp_handle *gt_handle(ATP ah)
{
    return (struct gt_atp_handle *)ah;
}

static int gt_addr_eq(const struct sockaddr_at *a,
                      const struct sockaddr_at *b)
{
    return a && b &&
           a->sat_addr.s_net == b->sat_addr.s_net &&
           a->sat_addr.s_node == b->sat_addr.s_node &&
           a->sat_port == b->sat_port;
}

static int gt_addr_accept(const struct sockaddr_at *filter,
                          const struct sockaddr_at *from)
{
    if (!filter || !from) {
        return 0;
    }

    if (filter->sat_addr.s_net != ATADDR_ANYNET &&
            filter->sat_addr.s_net != from->sat_addr.s_net) {
        return 0;
    }
    if (filter->sat_addr.s_node != ATADDR_ANYNODE &&
            filter->sat_addr.s_node != from->sat_addr.s_node) {
        return 0;
    }
    if (filter->sat_port != ATADDR_ANYPORT &&
            filter->sat_port != from->sat_port) {
        return 0;
    }
    return 1;
}

static void gt_trace(struct gt_atp_handle *g,
                     const char *event,
                     uint16_t tid,
                     unsigned int value)
{
    const char *path = getenv("GT_ATP_TRACE");
    FILE *f;

    if (!path || !*path) {
        return;
    }
    if (strcmp(path, "1") == 0) {
        path = "/tmp/gt-native-atp-r1.log";
    }

    f = fopen(path, "a");
    if (!f) {
        return;
    }

    fprintf(f,
            "GT_ATP event=%s tid=%u value=%u "
            "txreq=%lu rxresp=%lu rxreq=%lu retry=%lu timeout=%lu\n",
            event,
            (unsigned int)tid,
            value,
            g ? g->tx_treq : 0UL,
            g ? g->rx_tresp : 0UL,
            g ? g->rx_treq : 0UL,
            g ? g->retransmits : 0UL,
            g ? g->timeouts : 0UL);
    fclose(f);
}

static void gt_clear_responses(struct gt_atp_handle *g)
{
    unsigned int i;

    for (i = 0; i < ATP_MAXRESP; i++) {
        memset(&g->responses[i], 0, sizeof(g->responses[i]));
    }
}

static int gt_send_raw(struct gt_atp_handle *g,
                       const struct sockaddr_at *peer,
                       const void *data,
                       size_t len)
{
    ssize_t n;

    if (!g || !peer || !data || len == 0 || len > ATP_BUFSIZ) {
        errno = EINVAL;
        return -1;
    }

    n = netddp_sendto(g->pub.atph_socket,
                      data, len, 0,
                      (const struct sockaddr *)peer,
                      sizeof(*peer));
    if (n < 0) {
        return -1;
    }
    if ((size_t)n != len) {
        errno = EIO;
        return -1;
    }
    return 0;
}

static int gt_send_pending(struct gt_atp_handle *g, int retry)
{
    struct atphdr hdr;

    if (!g || !g->pending || g->request_len < ATP_HDRSIZE) {
        errno = EINVAL;
        return -1;
    }

    memcpy(&hdr, g->request + 1, sizeof(hdr));
    hdr.atphd_bitmap = g->pending_bitmap;
    memcpy(g->request + 1, &hdr, sizeof(hdr));

    if (gt_send_raw(g, &g->pending_peer,
                    g->request, g->request_len) < 0) {
        return -1;
    }

    g->tx_treq++;
    if (retry) {
        g->retransmits++;
    }
    gettimeofday(&g->pub.atph_reqtv, NULL);
    gt_trace(g, retry ? "retry" : "treq",
             g->pending_tid, g->pending_bitmap);
    return 0;
}

static int gt_send_release(struct gt_atp_handle *g)
{
    unsigned char packet[ATP_HDRSIZE + 4];
    struct atphdr hdr;

    if (!g || !g->pending || g->release_sent ||
            !(g->pending_ctrl & ATP_XO)) {
        return 0;
    }

    memset(packet, 0, sizeof(packet));
    memset(&hdr, 0, sizeof(hdr));
    packet[0] = DDPTYPE_ATP;
    hdr.atphd_ctrlinfo = ATP_TREL;
    hdr.atphd_bitmap = 0;
    hdr.atphd_tid = htons(g->pending_tid);
    memcpy(packet + 1, &hdr, sizeof(hdr));

    if (gt_send_raw(g, &g->pending_peer,
                    packet, sizeof(packet)) < 0) {
        return -1;
    }

    g->release_sent = 1;
    g->tx_trel++;
    gt_trace(g, "trel", g->pending_tid, 0);
    return 0;
}

static void gt_queue_push(struct gt_atp_handle *g,
                          const struct gt_packet *packet)
{
    unsigned int slot;

    if (g->queue_count == GT_QUEUE_MAX) {
        g->queue_head = (g->queue_head + 1U) % GT_QUEUE_MAX;
        g->queue_count--;
    }

    slot = (g->queue_head + g->queue_count) % GT_QUEUE_MAX;
    g->queue[slot] = *packet;
    g->queue[slot].valid = 1;
    g->queue_count++;
}

static int gt_queue_pop(struct gt_atp_handle *g,
                        struct gt_packet *packet)
{
    if (!g || !packet || g->queue_count == 0) {
        return 0;
    }

    *packet = g->queue[g->queue_head];
    memset(&g->queue[g->queue_head], 0,
           sizeof(g->queue[g->queue_head]));
    g->queue_head = (g->queue_head + 1U) % GT_QUEUE_MAX;
    g->queue_count--;
    return 1;
}

static int gt_resend_xo(struct gt_atp_handle *g,
                        const struct sockaddr_at *peer,
                        uint16_t tid,
                        uint8_t bitmap)
{
    int i;

    if (!g->xo.valid || g->xo.tid != tid ||
            !gt_addr_eq(&g->xo.peer, peer)) {
        return 0;
    }

    for (i = 0; i < g->xo.count; i++) {
        if ((bitmap & (1U << i)) && g->xo.packet[i].valid) {
            if (gt_send_raw(g, peer,
                            g->xo.packet[i].data,
                            g->xo.packet[i].len) < 0) {
                return -1;
            }
            g->tx_tresp++;
        }
    }

    g->duplicates++;
    gt_trace(g, "xo-resend", tid, bitmap);
    return 1;
}

static void gt_accept_response(struct gt_atp_handle *g,
                               const struct gt_packet *packet,
                               const struct atphdr *hdr)
{
    unsigned int seq = hdr->atphd_bitmap;
    unsigned int mask;

    if (seq >= ATP_MAXRESP || seq >= (unsigned int)g->pending_respcount) {
        g->bad_seq++;
        return;
    }
    if (!(g->pending_bitmap & (1U << seq))) {
        return;
    }

    g->responses[seq] = *packet;
    g->responses[seq].valid = 1;
    g->pending_bitmap &= (uint8_t)~(1U << seq);

    if (hdr->atphd_ctrlinfo & ATP_EOM) {
        mask = (1U << (seq + 1U)) - 1U;
        g->pending_bitmap &= (uint8_t)mask;
    }

    g->pub.atph_rbitmap = g->pending_bitmap;
    g->rx_tresp++;
    gt_trace(g, "tresp", g->pending_tid, g->pending_bitmap);
}

static int gt_receive_one(struct gt_atp_handle *g,
                          const struct sockaddr_at *filter,
                          int want_treq,
                          int want_tresp)
{
    struct gt_packet packet;
    struct sockaddr_at from;
    socklen_t fromlen = sizeof(from);
    struct atphdr hdr;
    ssize_t n;
    uint8_t func;
    uint16_t tid;
    int dup;

    memset(&packet, 0, sizeof(packet));
    memset(&from, 0, sizeof(from));

    n = netddp_recvfrom(g->pub.atph_socket,
                        packet.data, sizeof(packet.data), 0,
                        (struct sockaddr *)&from, &fromlen);
    if (n < 0) {
        return -1;
    }
    if (n < ATP_HDRSIZE || packet.data[0] != DDPTYPE_ATP) {
        return 0;
    }

    packet.valid = 1;
    packet.len = (size_t)n;
    packet.from = from;
    memcpy(&hdr, packet.data + 1, sizeof(hdr));
    func = hdr.atphd_ctrlinfo & ATP_FUNCMASK;
    tid = ntohs(hdr.atphd_tid);

    if (func == ATP_TREL) {
        g->rx_trel++;
        if (g->xo.valid && g->xo.tid == tid &&
                gt_addr_eq(&g->xo.peer, &from)) {
            memset(&g->xo, 0, sizeof(g->xo));
        }
        return 0;
    }

    if (func == ATP_TREQ) {
        g->rx_treq++;

        dup = gt_resend_xo(g, &from, tid, hdr.atphd_bitmap);
        if (dup < 0) {
            return -1;
        }
        if (dup > 0) {
            return 0;
        }

        if (!gt_addr_accept(filter, &from)) {
            g->wrong_peer++;
            return 0;
        }

        gt_queue_push(g, &packet);
        gt_trace(g, "incoming-treq", tid, hdr.atphd_bitmap);
        return want_treq ? ATP_TREQ : 0;
    }

    if (func == ATP_TRESP) {
        if (!g->pending) {
            g->wrong_tid++;
            return 0;
        }
        if (!gt_addr_eq(&g->pending_peer, &from)) {
            g->wrong_peer++;
            return 0;
        }
        if (tid != g->pending_tid) {
            g->wrong_tid++;
            return 0;
        }

        gt_accept_response(g, &packet, &hdr);

        if (hdr.atphd_ctrlinfo & ATP_STS) {
            if (gt_send_pending(g, 1) < 0) {
                return -1;
            }
        }

        if (g->pending_bitmap == 0) {
            if (gt_send_release(g) < 0) {
                return -1;
            }
            return want_tresp ? ATP_TRESP : 0;
        }
        return 0;
    }

    return 0;
}

static int gt_wait_readable(struct gt_atp_handle *g,
                            int timeout_sec)
{
    fd_set rfds;
    struct timeval tv;
    struct timeval *ptv = NULL;
    int rc;

    FD_ZERO(&rfds);
    FD_SET(g->pub.atph_socket, &rfds);

    if (timeout_sec >= 0) {
        tv.tv_sec = timeout_sec;
        tv.tv_usec = 0;
        ptv = &tv;
    }

    do {
        rc = select(g->pub.atph_socket + 1,
                    &rfds, NULL, NULL, ptv);
    } while (rc < 0 && errno == EINTR);

    return rc;
}

ATP atp_open(uint8_t port, const struct at_addr *saddr)
{
    struct gt_atp_handle *g;
    struct sockaddr_at addr;
    struct timeval tv;
    int s;
    int pid;

    memset(&addr, 0, sizeof(addr));
    addr.sat_port = port;
    if (saddr) {
        memcpy(&addr.sat_addr, saddr, sizeof(*saddr));
    }

    s = netddp_open(&addr, NULL);
    if (s < 0) {
        return NULL;
    }

    g = calloc(1, sizeof(*g));
    if (!g) {
        netddp_close(s);
        return NULL;
    }

    g->pub.atph_socket = s;
    g->pub.atph_saddr = addr;
    g->pub.atph_reqto = -1;

    gettimeofday(&tv, NULL);
    pid = getpid();
    g->pub.atph_tid = (uint16_t)(tv.tv_sec ^
                         (((pid << 8) & 0xff00) | (pid >> 8)));

    gt_trace(g, "open", g->pub.atph_tid,
             (unsigned int)g->pub.atph_saddr.sat_port);
    return &g->pub;
}

int atp_close(ATP ah)
{
    struct gt_atp_handle *g;
    int rc;

    if (!ah) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    gt_trace(g, "close", 0, 0);
    rc = netddp_close(g->pub.atph_socket);
    free(g);
    return rc;
}

int atp_sreq(ATP ah, struct atp_block *atpb,
             int respcount, uint8_t flags)
{
    struct gt_atp_handle *g;
    struct atphdr hdr;
    uint16_t tid;
    uint8_t bitmap;

    if (!ah || !atpb || !atpb->atp_saddr ||
            !atpb->atp_sreqdata ||
            atpb->atp_sreqdlen < 4 ||
            atpb->atp_sreqdlen > ATP_MAXDATA ||
            respcount < 0 || respcount > ATP_MAXRESP ||
            atpb->atp_sreqto < 0 ||
            (atpb->atp_sreqtries < 1 &&
             atpb->atp_sreqtries != ATP_TRIES_INFINITE)) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    if (g->pending) {
        errno = EBUSY;
        return -1;
    }

    gt_clear_responses(g);
    memset(g->request, 0, sizeof(g->request));
    bitmap = respcount == 0 ? 0U :
             (uint8_t)((1U << respcount) - 1U);
    tid = g->pub.atph_tid++;

    g->request[0] = DDPTYPE_ATP;
    memset(&hdr, 0, sizeof(hdr));
    hdr.atphd_ctrlinfo = (uint8_t)(ATP_TREQ | flags);
    hdr.atphd_bitmap = bitmap;
    hdr.atphd_tid = htons(tid);
    memcpy(g->request + 1, &hdr, sizeof(hdr));
    memcpy(g->request + ATP_HDRSIZE,
           atpb->atp_sreqdata,
           (size_t)atpb->atp_sreqdlen);

    g->request_len = ATP_HDRSIZE + (size_t)atpb->atp_sreqdlen;
    g->pending_peer = *atpb->atp_saddr;
    g->pending_tid = tid;
    g->pending_ctrl = hdr.atphd_ctrlinfo;
    g->pending_bitmap = bitmap;
    g->pending_respcount = respcount;
    g->timeout_sec = atpb->atp_sreqto;
    g->retries_left = atpb->atp_sreqtries == ATP_TRIES_INFINITE ?
                      ATP_TRIES_INFINITE : atpb->atp_sreqtries - 1;
    g->release_sent = 0;
    g->pending = respcount > 0 && atpb->atp_sreqto != 0;

    g->pub.atph_reqto = atpb->atp_sreqto;
    g->pub.atph_reqtries = g->retries_left;
    g->pub.atph_rrespcount = respcount;
    g->pub.atph_rbitmap = bitmap;
    atpb->atp_bitmap = bitmap;

    if (gt_send_raw(g, &g->pending_peer,
                    g->request, g->request_len) < 0) {
        g->pending = 0;
        return -1;
    }
    g->tx_treq++;
    gettimeofday(&g->pub.atph_reqtv, NULL);
    gt_trace(g, "treq", tid, bitmap);
    return 0;
}

int atp_rsel(ATP ah, struct sockaddr_at *faddr, int func)
{
    struct gt_atp_handle *g;
    int want_treq;
    int want_tresp;
    int rc;
    int wait_sec;

    if (!ah || !faddr) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    want_treq = func == 0 || (func & ATP_TREQ) != 0;
    want_tresp = func == 0 || (func & ATP_TRESP) != 0;

    if (want_treq && g->queue_count > 0) {
        return ATP_TREQ;
    }
    if (want_tresp && g->pending && g->pending_bitmap == 0) {
        return ATP_TRESP;
    }

    for (;;) {
        wait_sec = (g->pending && g->pending_bitmap != 0) ?
                   g->timeout_sec : -1;
        rc = gt_wait_readable(g, wait_sec);
        if (rc < 0) {
            return -1;
        }

        if (rc == 0) {
            if (!g->pending || g->pending_bitmap == 0) {
                errno = ETIMEDOUT;
                return -1;
            }

            if (g->retries_left == 0) {
                g->timeouts++;
                g->pub.atph_reqtries = 0;
                errno = ETIMEDOUT;
                gt_trace(g, "timeout", g->pending_tid,
                         g->pending_bitmap);
                return -1;
            }

            if (gt_send_pending(g, 1) < 0) {
                return -1;
            }
            if (g->retries_left > 0) {
                g->retries_left--;
            }
            g->pub.atph_reqtries = g->retries_left;
            continue;
        }

        rc = gt_receive_one(g, faddr, want_treq, want_tresp);
        if (rc < 0) {
            return -1;
        }
        if (rc != 0) {
            return rc;
        }

        if (want_treq && g->queue_count > 0) {
            return ATP_TREQ;
        }
        if (want_tresp && g->pending && g->pending_bitmap == 0) {
            return ATP_TRESP;
        }
    }
}

int atp_rresp(ATP ah, struct atp_block *atpb)
{
    struct gt_atp_handle *g;
    int rc;
    int i;
    size_t payload_len;

    if (!ah || !atpb || !atpb->atp_saddr ||
            !atpb->atp_rresiov ||
            atpb->atp_rresiovcnt <= 0 ||
            atpb->atp_rresiovcnt > ATP_MAXRESP) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    if (!g->pending) {
        errno = EINVAL;
        return -1;
    }

    while (g->pending_bitmap != 0) {
        rc = atp_rsel(ah, atpb->atp_saddr, ATP_TRESP);
        if (rc != ATP_TRESP) {
            return rc < 0 ? rc : -1;
        }
    }

    for (i = 0; i < ATP_MAXRESP; i++) {
        if (!g->responses[i].valid) {
            break;
        }
        if (i >= atpb->atp_rresiovcnt) {
            errno = EMSGSIZE;
            return -1;
        }
        if (g->responses[i].len < ATP_HDRSIZE) {
            errno = EPROTO;
            return -1;
        }

        payload_len = g->responses[i].len - ATP_HDRSIZE;
        if (payload_len > atpb->atp_rresiov[i].iov_len) {
            errno = EMSGSIZE;
            return -1;
        }

        memcpy(atpb->atp_rresiov[i].iov_base,
               g->responses[i].data + ATP_HDRSIZE,
               payload_len);
        atpb->atp_rresiov[i].iov_len = payload_len;
    }

    atpb->atp_rresiovcnt = i;
    gt_clear_responses(g);
    g->pending = 0;
    g->pending_bitmap = 0;
    g->pub.atph_rbitmap = 0;
    g->pub.atph_rrespcount = 0;
    g->pub.atph_reqtries = 0;
    return 0;
}

static int gt_pop_request_to_atpb(struct gt_atp_handle *g,
                                  struct atp_block *atpb)
{
    struct gt_packet packet;
    struct atphdr hdr;
    size_t payload_len;

    if (!gt_queue_pop(g, &packet)) {
        return 0;
    }
    if (packet.len < ATP_HDRSIZE) {
        errno = EPROTO;
        return -1;
    }

    memcpy(&hdr, packet.data + 1, sizeof(hdr));
    payload_len = packet.len - ATP_HDRSIZE;
    if ((size_t)atpb->atp_rreqdlen < payload_len) {
        errno = EMSGSIZE;
        return -1;
    }

    memcpy(atpb->atp_saddr, &packet.from, sizeof(packet.from));
    memcpy(atpb->atp_rreqdata,
           packet.data + ATP_HDRSIZE,
           payload_len);
    atpb->atp_rreqdlen = (int)payload_len;
    atpb->atp_bitmap = hdr.atphd_bitmap;

    g->pub.atph_rtid = ntohs(hdr.atphd_tid);
    g->pub.atph_rxo = hdr.atphd_ctrlinfo & ATP_XO;
    g->pub.atph_rreltime = ATP_RELTIME *
                            (1 << (hdr.atphd_ctrlinfo & ATP_TRELMASK));

    g->last_request_valid = 1;
    g->last_request_peer = packet.from;
    g->last_request_tid = g->pub.atph_rtid;
    g->last_request_ctrl = hdr.atphd_ctrlinfo;
    g->last_request_bitmap = hdr.atphd_bitmap;
    return 1;
}

int atp_rreq(ATP ah, struct atp_block *atpb)
{
    struct gt_atp_handle *g;
    int rc;

    if (!ah || !atpb || !atpb->atp_saddr ||
            !atpb->atp_rreqdata || atpb->atp_rreqdlen <= 0) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    if (g->queue_count == 0) {
        rc = atp_rsel(ah, atpb->atp_saddr, ATP_TREQ);
        if (rc != ATP_TREQ) {
            return rc < 0 ? rc : -1;
        }
    }

    rc = gt_pop_request_to_atpb(g, atpb);
    return rc == 1 ? 0 : -1;
}

int atp_rreq_try(ATP ah, struct atp_block *atpb)
{
    struct gt_atp_handle *g;
    fd_set rfds;
    struct timeval tv;
    int rc;

    if (!ah || !atpb || !atpb->atp_saddr ||
            !atpb->atp_rreqdata || atpb->atp_rreqdlen <= 0) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    rc = gt_pop_request_to_atpb(g, atpb);
    if (rc != 0) {
        return rc;
    }

    FD_ZERO(&rfds);
    FD_SET(g->pub.atph_socket, &rfds);
    tv.tv_sec = 0;
    tv.tv_usec = 0;
    rc = select(g->pub.atph_socket + 1,
                &rfds, NULL, NULL, &tv);
    if (rc < 0) {
        return -1;
    }
    if (rc == 0) {
        return 0;
    }

    rc = gt_receive_one(g, atpb->atp_saddr, 1, 1);
    if (rc < 0) {
        return -1;
    }
    return gt_pop_request_to_atpb(g, atpb);
}

int atp_sresp(ATP ah, struct atp_block *atpb)
{
    struct gt_atp_handle *g;
    struct atphdr hdr;
    unsigned char packet[ATP_BUFSIZ];
    int i;
    size_t packet_len;

    if (!ah || !atpb || !atpb->atp_saddr ||
            !atpb->atp_sresiov ||
            atpb->atp_sresiovcnt < 1 ||
            atpb->atp_sresiovcnt > ATP_MAXRESP) {
        errno = EINVAL;
        return -1;
    }

    g = gt_handle(ah);
    if (!g->last_request_valid) {
        errno = EPROTO;
        return -1;
    }

    memset(&g->xo, 0, sizeof(g->xo));

    for (i = 0; i < atpb->atp_sresiovcnt; i++) {
        if (atpb->atp_sresiov[i].iov_len > ATP_MAXDATA) {
            errno = EMSGSIZE;
            return -1;
        }

        memset(packet, 0, sizeof(packet));
        memset(&hdr, 0, sizeof(hdr));
        packet[0] = DDPTYPE_ATP;
        hdr.atphd_ctrlinfo = ATP_TRESP;
        if (i == atpb->atp_sresiovcnt - 1) {
            hdr.atphd_ctrlinfo |= ATP_EOM;
        }
        hdr.atphd_bitmap = (uint8_t)i;
        hdr.atphd_tid = htons(g->last_request_tid);
        memcpy(packet + 1, &hdr, sizeof(hdr));
        memcpy(packet + ATP_HDRSIZE,
               atpb->atp_sresiov[i].iov_base,
               atpb->atp_sresiov[i].iov_len);
        packet_len = ATP_HDRSIZE + atpb->atp_sresiov[i].iov_len;

        if (gt_send_raw(g, atpb->atp_saddr,
                        packet, packet_len) < 0) {
            return -1;
        }
        g->tx_tresp++;

        if (g->last_request_ctrl & ATP_XO) {
            g->xo.packet[i].valid = 1;
            g->xo.packet[i].len = packet_len;
            g->xo.packet[i].from = *atpb->atp_saddr;
            memcpy(g->xo.packet[i].data, packet, packet_len);
        }
    }

    if (g->last_request_ctrl & ATP_XO) {
        g->xo.valid = 1;
        g->xo.peer = *atpb->atp_saddr;
        g->xo.tid = g->last_request_tid;
        g->xo.count = atpb->atp_sresiovcnt;
    }

    gt_trace(g, "sresp", g->last_request_tid,
             (unsigned int)atpb->atp_sresiovcnt);
    g->last_request_valid = 0;
    return 0;
}
