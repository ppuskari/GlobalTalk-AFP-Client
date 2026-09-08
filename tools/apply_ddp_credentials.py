#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Add credentials to the GlobalTalk afp+ddp:// authority parser.
#
# Supported forms:
#   afp+ddp://object@zone/volume/path
#   afp+ddp://user:password@object@zone/volume/path
#   afp+ddp://user@object@zone/volume/path
#   afp+ddp://user:password@object/volume/path   (default zone *)
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK DDP CREDENTIALS"


def die(msg):
    raise SystemExit("apply_ddp_credentials: " + msg)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_ddp_credentials.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "lib", "afp_url.c")

    if not os.path.isfile(path):
        die("afp_url.c not found: {}".format(path))

    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if MARKER in text:
        print("DDP credential parser already present: {}".format(path))
        return

    old_decl = """    char *at;\n    char authority[AFP_HOSTNAME_LEN];\n"""
    new_decl = """    char *at;\n    char *first_at;\n    char *colon;\n    char *object;\n    char authority[AFP_HOSTNAME_LEN];\n"""

    if text.count(old_decl) != 1:
        die("DDP parser declaration guard missing/non-unique")
    text = text.replace(old_decl, new_decl, 1)

    old = """    at = strrchr(authority, '@');\n    if (at) {\n        size_t objlen = (size_t)(at - authority);\n        if (objlen == 0 || objlen >= sizeof(url->servername)) {\n            return -1;\n        }\n\n        memcpy(url->servername, authority, objlen);\n        url->servername[objlen] = '\\0';\n        strlcpy(url->zone, at + 1, sizeof(url->zone));\n    } else {\n        strlcpy(url->servername, authority, sizeof(url->servername));\n    }\n"""

    new = """    /* GLOBALTALK DDP CREDENTIALS\n     * Authority is [user[:password]@]object[@zone].  The final '@' is\n     * always the AppleTalk zone separator; when two '@' characters are\n     * present, the first separates AFP credentials from the NBP object. */\n    first_at = strchr(authority, '@');\n    at = strrchr(authority, '@');\n    object = authority;\n\n    if (first_at && at && first_at != at) {\n        *first_at = '\\0';\n        object = first_at + 1;\n\n        colon = strchr(authority, ':');\n        if (colon) {\n            *colon = '\\0';\n            strlcpy(url->username, authority, sizeof(url->username));\n            strlcpy(url->password, colon + 1, sizeof(url->password));\n        } else {\n            strlcpy(url->username, authority, sizeof(url->username));\n        }\n\n        if (at <= object || at[1] == '\\0') {\n            return -1;\n        }\n        *at = '\\0';\n        strlcpy(url->zone, at + 1, sizeof(url->zone));\n    } else if (at) {\n        colon = strchr(authority, ':');\n\n        if (colon && colon < at) {\n            /* One '@' plus user:password means credentials with the\n             * default AppleTalk zone. */\n            *at = '\\0';\n            *colon = '\\0';\n            strlcpy(url->username, authority, sizeof(url->username));\n            strlcpy(url->password, colon + 1, sizeof(url->password));\n            object = at + 1;\n        } else {\n            /* Legacy object@zone form. */\n            *at = '\\0';\n            object = authority;\n            if (at[1] == '\\0') {\n                return -1;\n            }\n            strlcpy(url->zone, at + 1, sizeof(url->zone));\n        }\n    }\n\n    if (object[0] == '\\0'\n            || strlcpy(url->servername, object, sizeof(url->servername))\n               >= sizeof(url->servername)) {\n        return -1;\n    }\n"""

    if text.count(old) != 1:
        die("DDP authority parser guard missing/non-unique")

    text = text.replace(old, new, 1)

    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)

    print("DDP credential parser ready: {}".format(path))


if __name__ == "__main__":
    main()
