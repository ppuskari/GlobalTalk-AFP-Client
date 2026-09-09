#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Diagnostic-only overlay for AFP 2.x date investigation.
# Logs the raw FPGetSrvrParms server clock and raw AFP file date words without
# changing protocol behavior.  Requires the R2 date-normalization overlay to
# have been applied first.  Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK AFP2 DATE WIRE DIAG R1"


def die(msg):
    raise SystemExit("apply_afp2_date_wire_diag: " + msg)


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
        die("usage: apply_afp2_date_wire_diag.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    server_path = os.path.join(root, "lib", "proto_server.c")
    reply_path = os.path.join(root, "lib", "proto_replyblock.c")

    for path in (server_path, reply_path):
        if not os.path.isfile(path):
            die("missing {}".format(path))

    server = read_text(server_path)
    reply = read_text(reply_path)

    if MARKER in server and MARKER in reply:
        print("AFP 2.x date wire diagnostic already applied: {}".format(root))
        return

    if "GLOBALTALK AFP2 DATE NORMALIZATION R1" not in read_text(
            os.path.join(root, "include", "afp.h")):
        die("AFP 2.x date normalization R1 must be applied first")

    if MARKER not in server:
        server = replace_once(
            server,
            "#include <stdint.h>\n#include <time.h>\n",
            "#include <stdint.h>\n#include <time.h>\n#include <stdio.h>\n",
            "proto_server.c stdio include")

        anchor = """static int server_uses_local_time(const struct afp_server *server)\n{\n"""
        helper = r'''/* GLOBALTALK AFP2 DATE WIRE DIAG R1 */
static void gt_afp_date_trace_server(const struct afp_server *server,
                                     uint32_t wire_date)
{
    const char *path = getenv("GT_AFP_DATE_TRACE");
    FILE *fp;
    uint32_t host_raw;
    int32_t signed_raw;
    time_t now;
    time_t server_clock;
    int version = 0;

    if (!path || !*path) {
        return;
    }

    fp = fopen(path, "a");
    if (!fp) {
        return;
    }

    host_raw = ntohl(wire_date);
    signed_raw = (int32_t)host_raw;
    now = time(NULL);
    server_clock = afp_date_to_unix(NULL, wire_date);

    if (server && server->using_version) {
        version = server->using_version->av_number;
    }

    fprintf(fp,
            "SRVR version=%d raw=0x%08x signed=%d "
            "server_unix=%lld local_unix=%lld offset=%lld\\n",
            version,
            (unsigned int)host_raw,
            (int)signed_raw,
            (long long)server_clock,
            (long long)now,
            (long long)(server ? server->time_offset : 0));
    fclose(fp);
}

'''
        server = replace_once(
            server, anchor, helper + anchor,
            "proto_server.c diagnostic helper")

        old = """    server->num_volumes = afp_getsrvparm_reply->numvolumes;\n"""
        new = """    gt_afp_date_trace_server(server, afp_getsrvparm_reply->time);\n\n    server->num_volumes = afp_getsrvparm_reply->numvolumes;\n"""
        server = replace_once(
            server, old, new,
            "proto_server.c diagnostic call")

    if MARKER not in reply:
        reply = replace_once(
            reply,
            "#include <string.h>\n",
            "#include <string.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\n",
            "proto_replyblock.c diagnostic includes")

        helper_anchor = """static int need_bytes(const char *p, const char *end, size_t len)\n{\n"""
        helper = r'''/* GLOBALTALK AFP2 DATE WIRE DIAG R1 */
static void gt_afp_date_trace_file(const struct afp_server *server,
                                   const struct afp_file_info *filecur,
                                   unsigned char isdir,
                                   unsigned short bitmap,
                                   int have_create,
                                   uint32_t create_raw,
                                   int have_modify,
                                   uint32_t modify_raw)
{
    const char *path = getenv("GT_AFP_DATE_TRACE");
    FILE *fp;
    int version = 0;

    if (!path || !*path || (!have_create && !have_modify)) {
        return;
    }

    fp = fopen(path, "a");
    if (!fp) {
        return;
    }

    if (server && server->using_version) {
        version = server->using_version->av_number;
    }

    fprintf(fp,
            "FILE version=%d isdir=%u bitmap=0x%04x "
            "name=%s create_raw=%s0x%08x create_signed=%d create_unix=%u "
            "modify_raw=%s0x%08x modify_signed=%d modify_unix=%u "
            "offset=%lld\\n",
            version,
            (unsigned int)isdir,
            (unsigned int)bitmap,
            filecur->name[0] ? filecur->name : "<unnamed>",
            have_create ? "" : "-",
            (unsigned int)create_raw,
            have_create ? (int32_t)create_raw : 0,
            (unsigned int)filecur->creation_date,
            have_modify ? "" : "-",
            (unsigned int)modify_raw,
            have_modify ? (int32_t)modify_raw : 0,
            (unsigned int)filecur->modification_date,
            (long long)(server ? server->time_offset : 0));
    fclose(fp);
}

'''
        reply = replace_once(
            reply, helper_anchor, helper + helper_anchor,
            "proto_replyblock.c diagnostic helper")

        old = """    unsigned short bitmap;\n    const char *p2, *end;\n"""
        new = """    unsigned short bitmap;\n    const char *p2, *end;\n    uint32_t gt_create_raw = 0;\n    uint32_t gt_modify_raw = 0;\n    int gt_have_create = 0;\n    int gt_have_modify = 0;\n"""
        reply = replace_once(
            reply, old, new,
            "proto_replyblock.c diagnostic locals")

        old = """        filecur->creation_date = afp_date_to_unix(server, *date);\n        p2 += 4;\n"""
        new = """        gt_create_raw = ntohl(*date);\n        gt_have_create = 1;\n        filecur->creation_date = afp_date_to_unix(server, *date);\n        p2 += 4;\n"""
        reply = replace_once(
            reply, old, new,
            "proto_replyblock.c create raw capture")

        old = """        filecur->modification_date = afp_date_to_unix(server, *date);\n        p2 += 4;\n"""
        new = """        gt_modify_raw = ntohl(*date);\n        gt_have_modify = 1;\n        filecur->modification_date = afp_date_to_unix(server, *date);\n        p2 += 4;\n"""
        reply = replace_once(
            reply, old, new,
            "proto_replyblock.c modify raw capture")

        old = """    return 0;\n}\n"""
        pos = reply.rfind(old)
        if pos < 0:
            die("proto_replyblock.c final return guard missing")
        new = """    gt_afp_date_trace_file(server, filecur, isdir, bitmap,\n                           gt_have_create, gt_create_raw,\n                           gt_have_modify, gt_modify_raw);\n\n    return 0;\n}\n"""
        reply = reply[:pos] + new + reply[pos + len(old):]

    write_text(server_path, server)
    write_text(reply_path, reply)

    print("Applied AFP 2.x date wire diagnostic: {}".format(root))
    print("  GT_AFP_DATE_TRACE=/path logs FPGetSrvrParms raw server time")
    print("  logs raw create/modify words and normalized values per reply")
    print("  no AFP/ASP/ATP behavior is changed")


if __name__ == "__main__":
    main()
