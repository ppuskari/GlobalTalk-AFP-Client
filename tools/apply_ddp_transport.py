#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Apply the AFP-over-DDP overlay to an exact Netatalk Client 0.9.5 checkout.
# Every edit is guarded. If an expected 0.9.5 fragment is absent or appears
# more than once, abort rather than producing a partial patch.

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
UP = (Path(sys.argv[1]).resolve()
      if len(sys.argv) > 1
      else ROOT / "work" / "netatalk-client")


def die(msg):
    raise SystemExit("apply_ddp_transport: " + msg)


def replace_once(path, old, new):
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}: {!r}".format(
            path, count, old[:72]))
    path.write_text(text.replace(old, new, 1))


if not (UP / "meson.build").exists():
    die("not a Netatalk Client checkout: {}".format(UP))

# Python 3.4 pathlib predates the os.PathLike protocol, so shutil needs
# ordinary strings rather than Path objects.
shutil.copy2(str(ROOT / "overlay/include/asp_transport.h"),
             str(UP / "include/asp_transport.h"))
shutil.copy2(str(ROOT / "overlay/lib/asp_transport.c"),
             str(UP / "lib/asp_transport.c"))

# ----------------------------------------------------------------------
# include/afp.h: private ASP transport context.
# ----------------------------------------------------------------------
p = UP / "include/afp.h"
replace_once(
    p,
    "    void *dsi;\n    unsigned int exit_flag;\n",
    "    void *dsi;\n"
    "    /* AFP-over-DDP/ASP transport context. */\n"
    "    void *asp;\n"
    "    unsigned int exit_flag;\n",
)

# ----------------------------------------------------------------------
# include/dsi.h: ASP GetStatus reuses the existing status decoder.
# ----------------------------------------------------------------------
p = UP / "include/dsi.h"
replace_once(
    p,
    "int dsi_getstatus(struct afp_server * server);\n",
    "int dsi_getstatus(struct afp_server * server);\n"
    "void dsi_getstatus_reply(struct afp_server * server);\n",
)

# ----------------------------------------------------------------------
# lib/meson.build: compile adapter and link Netatalk 4.5.x libatalk.
# ----------------------------------------------------------------------
p = UP / "lib/meson.build"
replace_once(
    p,
    "    'afp.c',\n",
    "    'afp.c',\n"
    "    'asp_transport.c',\n",
)
replace_once(
    p,
    "libafpclient = shared_library(\n",
    "libatalk_dep = cc.find_library('atalk', required: true)\n\n"
    "libafpclient = shared_library(\n",
)
replace_once(
    p,
    "    dependencies: [root_dependencies, libiconv_dep, gcrypt_dep, pthread_dep],\n",
    "    dependencies: [root_dependencies, libiconv_dep, gcrypt_dep, "
    "pthread_dep, libatalk_dep],\n",
)

# ----------------------------------------------------------------------
# lib/connect.c: route afp+ddp URLs before DNS/TCP resolution.
# ----------------------------------------------------------------------
p = UP / "lib/connect.c"
replace_once(
    p,
    '#include "server.h"\n',
    '#include "server.h"\n'
    '#include "asp_transport.h"\n',
)
replace_once(
    p,
    "    unsigned int rx_quantum;\n"
    "    char icon[AFP_SERVER_ICON_LEN];\n\n",
    "    unsigned int rx_quantum;\n"
    "    char icon[AFP_SERVER_ICON_LEN];\n\n"
    "    if (req->url.protocol == AT) {\n"
    "        return asp_transport_full_connect(priv, req);\n"
    "    }\n\n",
)

# ----------------------------------------------------------------------
# lib/afp.c:
# - dispatch configured ASP servers before TCP socket work
# - keep them on the normal server list
# - destroy ASP state during normal server removal
# ----------------------------------------------------------------------
p = UP / "lib/afp.c"
text = p.read_text()

# Put include after a stable local include if not already present.
include_guard = '#include "dsi.h"\n'
if '#include "asp_transport.h"\n' not in text:
    if include_guard not in text:
        die("lib/afp.c: cannot find dsi.h include")
    text = text.replace(
        include_guard,
        include_guard + '#include "asp_transport.h"\n',
        1,
    )
p.write_text(text)

replace_once(
    p,
    "    address = server->address;\n"
    "    server->data_read = 0;\n"
    "    server->attention_len = 0;\n\n",
    "    address = server->address;\n"
    "    server->data_read = 0;\n"
    "    server->attention_len = 0;\n\n"
    "    if (server->asp) {\n"
    "        if (asp_transport_connect(server, full) < 0) {\n"
    "            return -errno;\n"
    "        }\n"
    "\n"
    "        server->exit_flag = 0;\n"
    "        server->connect_state = SERVER_STATE_CONNECTING;\n"
    "\n"
    "        int found = 0;\n"
    "        for (struct afp_server *s = get_server_base(); s; s = s->next) {\n"
    "            if (s == server) {\n"
    "                found = 1;\n"
    "                break;\n"
    "            }\n"
    "        }\n"
    "        if (!found) {\n"
    "            add_server(server);\n"
    "        }\n"
    "\n"
    "        afp_server_next_connection_generation(server);\n"
    "        afp_server_identify(server);\n"
    "        return 0;\n"
    "    }\n\n",
)

replace_once(
    p,
    "    /* Close the connection */\n"
    "    loop_disconnect(s);\n",
    "    /* Close the connection */\n"
    "    if (s->asp) {\n"
    "        asp_transport_destroy(s);\n"
    "    }\n"
    "    loop_disconnect(s);\n",
)

# ----------------------------------------------------------------------
# lib/server.c: do not register an ATP/DDP fd in DSI's TCP receive loop.
# dsi_opensession() itself is patched to call ASP OpenSession.
# ----------------------------------------------------------------------
p = UP / "lib/server.c"
text = p.read_text()
if '#include "asp_transport.h"\n' not in text:
    guard = '#include "dsi.h"\n'
    if guard not in text:
        die("lib/server.c: cannot find dsi.h include")
    text = text.replace(
        guard,
        guard + '#include "asp_transport.h"\n',
        1,
    )
p.write_text(text)

replace_once(
    p,
    "    add_fd_and_signal(server->fd);\n\n"
    "    if (dsi_opensession(server) != 0) {\n",
    "    if (!server->asp) {\n"
    "        add_fd_and_signal(server->fd);\n"
    "    }\n\n"
    "    if (dsi_opensession(server) != 0) {\n",
)

replace_once(
    p,
    '"Could not open DSI session");',
    '"Could not open AFP transport session");',
)

# ----------------------------------------------------------------------
# lib/dsi.c: synchronous ASP short-circuits.
# ----------------------------------------------------------------------
p = UP / "lib/dsi.c"
text = p.read_text()
if '#include "asp_transport.h"\n' not in text:
    guard = '#include "codepage.h"\n'
    if guard not in text:
        die("lib/dsi.c: cannot find codepage include")
    text = text.replace(
        guard,
        guard + '#include "asp_transport.h"\n',
        1,
    )
p.write_text(text)

replace_once(
    p,
    "int dsi_getstatus(struct afp_server * server)\n{\n",
    "int dsi_getstatus(struct afp_server * server)\n{\n"
    "    if (server && server->asp) {\n"
    "        return asp_transport_connect(server, 1);\n"
    "    }\n",
)

replace_once(
    p,
    "int dsi_sendtickle(struct afp_server *server)\n{\n",
    "int dsi_sendtickle(struct afp_server *server)\n{\n"
    "    if (server && server->asp) {\n"
    "        return asp_transport_tickle(server);\n"
    "    }\n",
)

replace_once(
    p,
    "int dsi_opensession(struct afp_server *server)\n{\n",
    "int dsi_opensession(struct afp_server *server)\n{\n"
    "    if (server && server->asp) {\n"
    "        return asp_transport_open_session(server);\n"
    "    }\n",
)

replace_once(
    p,
    "int dsi_send(struct afp_server *server, char * msg, int size, int wait,\n"
    "             unsigned char subcommand, void **other)\n{\n",
    "int dsi_send(struct afp_server *server, char * msg, int size, int wait,\n"
    "             unsigned char subcommand, void **other)\n{\n"
    "    if (server && server->asp) {\n"
    "        return asp_transport_send(server, msg, size, wait,\n"
    "                                  subcommand, other);\n"
    "    }\n",
)

# ----------------------------------------------------------------------
# lib/afp_url.c: add guest-oriented afp+ddp://OBJECT@ZONE/VOLUME/path.
# ----------------------------------------------------------------------
p = UP / "lib/afp_url.c"
text = p.read_text()
marker = "/* The most complex AFP URL is:\n"
if text.count(marker) != 1:
    die("lib/afp_url.c: URL helper insertion marker missing/non-unique")

helper = r"""
static int parse_ddp_url(struct afp_url *url, const char *toparse)
{
    const char *prefix = "afp+ddp://";
    const char *p;
    const char *slash;
    char *at;
    char authority[AFP_HOSTNAME_LEN];
    size_t n;

    if (strncmp(toparse, prefix, strlen(prefix)) != 0) {
        return 1; /* not a DDP URL */
    }

    url->protocol = AT;
    url->port = 0;
    url->username[0] = '\0';
    url->password[0] = '\0';
    url->uamname[0] = '\0';
    url->volumename[0] = '\0';
    url->path[0] = '\0';
    strlcpy(url->zone, "*", sizeof(url->zone));

    p = toparse + strlen(prefix);
    slash = strchr(p, '/');
    n = slash ? (size_t)(slash - p) : strlen(p);

    if (n == 0 || n >= sizeof(authority)) {
        return -1;
    }

    memcpy(authority, p, n);
    authority[n] = '\0';

    at = strrchr(authority, '@');
    if (at) {
        size_t objlen = (size_t)(at - authority);
        if (objlen == 0 ||
                objlen >= sizeof(url->servername)) {
            return -1;
        }

        memcpy(url->servername, authority, objlen);
        url->servername[objlen] = '\0';
        strlcpy(url->zone, at + 1,
                sizeof(url->zone));
    } else {
        strlcpy(url->servername, authority,
                sizeof(url->servername));
    }

    if (!slash || !slash[1]) {
        return 0;
    }

    p = slash + 1;
    slash = strchr(p, '/');
    n = slash ? (size_t)(slash - p) : strlen(p);

    if (n >= sizeof(url->volumename)) {
        return -1;
    }

    memcpy(url->volumename, p, n);
    url->volumename[n] = '\0';

    if (slash && slash[1]) {
        strlcpy(url->path, slash + 1,
                sizeof(url->path));
    }

    return 0;
}

"""

text = text.replace(marker, helper + marker, 1)

old = (
    "int afp_parse_url(struct afp_url * url, const char * toparse)\n"
    "{\n"
    "    char firstpart[AFP_HOSTNAME_LEN], secondpart[MAX_CLIENT_RESPONSE];\n"
)
new = (
    "int afp_parse_url(struct afp_url * url, const char * toparse)\n"
    "{\n"
    "    int ddp_rc = parse_ddp_url(url, toparse);\n"
    "    if (ddp_rc <= 0) {\n"
    "        return ddp_rc;\n"
    "    }\n"
    "\n"
    "    url->protocol = TCPIP;\n"
    "    char firstpart[AFP_HOSTNAME_LEN], secondpart[MAX_CLIENT_RESPONSE];\n"
)

if text.count(old) != 1:
    die("lib/afp_url.c: afp_parse_url guard missing/non-unique")
p.write_text(text.replace(old, new, 1))

print("AFP-over-DDP overlay applied to: {}".format(UP))