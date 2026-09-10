#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Opt-in classic Finder-compatible AFP 2.x date interpretation.
#
# Field captures from a real Macintosh and GlobalTalk server showed the same
# raw AFP date words on the wire.  Netatalk Client's standards-correct signed
# AFP-2000 decode produced 1984/1985, while classic Finder displayed matching
# 2020/2021 dates.  The observed mapping is reproduced by treating the raw
# high-bit value with an alternate fixed era offset of 2209075200 seconds,
# then applying the normal AFP 2.x server clock correction.
#
# This patch is intentionally opt-in and read-only:
#   GT_AFP_DATE_COMPAT=legacy1900
# or:
#   GT_AFP_DATE_COMPAT=1
#
# Standards behavior remains the default.  Upload/set-date encoding is not
# changed until classic write-side semantics are independently proven.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK AFP2 LEGACY DATE COMPAT R4"


def die(msg):
    raise SystemExit("apply_afp2_legacy_date_compat_r4: " + msg)


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


def main():
    if len(sys.argv) != 2:
        die("usage: apply_afp2_legacy_date_compat_r4.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    afp_h = os.path.join(root, "include", "afp.h")
    path = os.path.join(root, "lib", "proto_server.c")

    if not os.path.isfile(path) or not os.path.isfile(afp_h):
        die("not a Netatalk Client tree: {}".format(root))

    if "GLOBALTALK AFP2 DATE NORMALIZATION R1" not in read_text(afp_h):
        die("AFP 2.x date normalization R1 must be applied first")

    text = read_text(path)
    if MARKER in text:
        print("AFP 2.x legacy date compatibility already applied: {}".format(root))
        return

    anchor = """static int server_uses_local_time(const struct afp_server *server)\n{\n    return server && server->using_version\n           && server->using_version->av_number < 30;\n}\n\n"""

    helper = r'''/* GLOBALTALK AFP2 LEGACY DATE COMPAT R4 */
#define GT_AFP_LEGACY_ERA_OFFSET INT64_C(2209075200)
#define GT_AFP_LEGACY_MIN_UNIX   INT64_C(946684800)   /* 2000-01-01 */
#define GT_AFP_LEGACY_MAX_UNIX   INT64_C(2208988800)  /* 2040-01-01 */

static int gt_afp_legacy_date_compat_enabled(void)
{
    const char *value = getenv("GT_AFP_DATE_COMPAT");

    if (!value || !*value) {
        return 0;
    }

    return strcmp(value, "1") == 0
           || strcmp(value, "legacy1900") == 0
           || strcmp(value, "finder") == 0;
}

static int gt_afp_legacy_date_candidate(const struct afp_server *server,
                                        uint32_t wire_seconds,
                                        int64_t signed_unix,
                                        time_t *result)
{
    int64_t legacy;

    if (!result || !server_uses_local_time(server)
            || !gt_afp_legacy_date_compat_enabled()) {
        return 0;
    }

    /* Only reinterpret high-bit values whose standards decode is pre-2000. */
    if (!(wire_seconds & UINT32_C(0x80000000))
            || signed_unix >= GT_AFP_LEGACY_MIN_UNIX) {
        return 0;
    }

    legacy = (int64_t)wire_seconds - GT_AFP_LEGACY_ERA_OFFSET;
    legacy -= server->time_offset;

    /* Keep the compatibility window deliberately narrow while we collect
     * more field evidence from classic archive servers. */
    if (legacy < GT_AFP_LEGACY_MIN_UNIX
            || legacy >= GT_AFP_LEGACY_MAX_UNIX) {
        return 0;
    }

    *result = (time_t)legacy;
    return 1;
}

'''

    text = replace_once(text, anchor, anchor + helper,
                        "proto_server.c compatibility helper")

    old = """    seconds += AD_DATE_DELTA;\n\n    if (server_uses_local_time(server)) {\n        seconds -= server->time_offset;\n    }\n\n    return (time_t)seconds;\n"""

    new = """    seconds += AD_DATE_DELTA;\n\n    if (server_uses_local_time(server)) {\n        time_t legacy_result;\n\n        if (gt_afp_legacy_date_candidate(server, wire_seconds,\n                                         seconds, &legacy_result)) {\n            return legacy_result;\n        }\n\n        seconds -= server->time_offset;\n    }\n\n    return (time_t)seconds;\n"""

    text = replace_once(text, old, new,
                        "proto_server.c afp_date_to_unix hook")

    write_text(path, text)

    print("Applied AFP 2.x legacy date compatibility R4: {}".format(root))
    print("  default signed AFP-2000 decode remains unchanged")
    print("  GT_AFP_DATE_COMPAT=legacy1900 enables classic Finder mapping")
    print("  only high-bit pre-2000 reads with a 2000-2039 alternate are remapped")
    print("  AFP date writes remain standards-correct and unchanged")
    print("  DDP/ATP/ASP transport is unchanged")


if __name__ == "__main__":
    main()
