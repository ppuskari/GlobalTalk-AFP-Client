#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Canonical rooted afp+ddp:// URL overlay.
#
# Classic AFP paths handed to the stateless helper must remain rooted after
# the volume name.  This is the hardware-proven behavior used by R2A/R2F.
# The patcher accepts either a clean Netatalk Client 0.9.5 afp_url.c or an
# already-inserted GlobalTalk DDP parser and is safe to run repeatedly.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "afp_url.c")
MARKER = "GLOBALTALK ROOTED DDP URL"


def die(msg):
    raise SystemExit("apply_ddp_rooted_url: " + msg)


if not os.path.isfile(PATH):
    die("afp_url.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

rooted = """    if (slash && slash[1]) {\n        url->path[0] = '/';\n        strlcpy(url->path + 1, slash + 1,\n                sizeof(url->path) - 1);\n    }\n"""

unrooted = """    if (slash && slash[1]) {\n        strlcpy(url->path, slash + 1,\n                sizeof(url->path));\n    }\n"""

# Existing DDP parser: normalize only the path behavior.
if "static int parse_ddp_url(" in text:
    if rooted in text:
        print("Rooted DDP URL parser already present: {}".format(PATH))
        raise SystemExit(0)

    if text.count(unrooted) != 1:
        die("existing DDP parser has unexpected pathname form")

    text = text.replace(
        unrooted,
        "    /* {} */\n".format(MARKER) + rooted,
        1,
    )

    with io.open(PATH, "w", encoding="utf-8") as f:
        f.write(text)

    print("Updated DDP URL parser to rooted paths: {}".format(PATH))
    raise SystemExit(0)

# Clean pinned upstream source: recreate the GlobalTalk DDP URL parser.
insertion_marker = "/* The most complex AFP URL is:\n"
if text.count(insertion_marker) != 1:
    die("URL helper insertion marker missing/non-unique")

helper = r'''/* GLOBALTALK ROOTED DDP URL */
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
        if (objlen == 0 || objlen >= sizeof(url->servername)) {
            return -1;
        }

        memcpy(url->servername, authority, objlen);
        url->servername[objlen] = '\0';
        strlcpy(url->zone, at + 1, sizeof(url->zone));
    } else {
        strlcpy(url->servername, authority, sizeof(url->servername));
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
        url->path[0] = '/';
        strlcpy(url->path + 1, slash + 1,
                sizeof(url->path) - 1);
    }

    return 0;
}

'''

text = text.replace(insertion_marker, helper + insertion_marker, 1)

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
    die("afp_parse_url guard missing/non-unique")

text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Rebuilt rooted afp+ddp URL parser: {}".format(PATH))
