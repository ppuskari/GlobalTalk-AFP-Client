/*
 * GlobalTalk AFP Client -- AFP-over-DDP/ASP transport
 * SPDX-License-Identifier: GPL-2.0-only
 */

#ifndef AFPC_ASP_TRANSPORT_H
#define AFPC_ASP_TRANSPORT_H

#include "afp.h"

#define AFPC_ASP_COMMAND_DATA 578U
#define AFPC_ASP_MAX_PACKETS 8U
#define AFPC_ASP_MAX_DATA \
    (AFPC_ASP_COMMAND_DATA * AFPC_ASP_MAX_PACKETS)

struct afp_connection_request;

int asp_transport_configure(struct afp_server *server,
                            const char *object,
                            const char *zone);
int asp_transport_connect(struct afp_server *server,
                          int full_status);
int asp_transport_open_session(struct afp_server *server);
int asp_transport_send(struct afp_server *server,
                       const char *dsi_msg,
                       int dsi_size,
                       int wait,
                       unsigned char subcommand,
                       void *other);
int asp_transport_tickle(struct afp_server *server);
void asp_transport_close_session(struct afp_server *server);
void asp_transport_destroy(struct afp_server *server);

struct afp_server *
asp_transport_full_connect(void *priv,
                           struct afp_connection_request *req);

#endif
