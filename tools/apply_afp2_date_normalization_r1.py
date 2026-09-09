#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Backport the post-0.9.5 AFP 2.x date normalization used by Netatalk Client.
#
# Classic AFP 2.x servers return date fields in the server's local clock time.
# FPGetSrvrParms also returns the server's current clock, allowing the client
# to establish a server-minus-client offset and express later AFP dates on the
# client's Unix time base.  Netatalk Client 0.9.5 predates this normalization;
# a classic server with a badly wrong clock can therefore shift every file
# creation/modification date by years or decades.
#
# This guarded overlay mirrors the newer upstream logic without touching the
# DDP/ATP/ASP transport.  Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK AFP2 DATE NORMALIZATION R1"


def die(msg):
    raise SystemExit("apply_afp2_date_normalization_r1: " + msg)


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


def replace_count(text, old, new, expected, what):
    count = text.count(old)
    if count != expected:
        die("{}: expected {} guards, found {}".format(
            what, expected, count))
    return text.replace(old, new)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_afp2_date_normalization_r1.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    paths = {
        "afp_h": os.path.join(root, "include", "afp.h"),
        "internal": os.path.join(root, "lib", "afp_internal.h"),
        "server": os.path.join(root, "lib", "proto_server.c"),
        "reply": os.path.join(root, "lib", "proto_replyblock.c"),
        "volume": os.path.join(root, "lib", "proto_volume.c"),
        "files": os.path.join(root, "lib", "proto_files.c"),
    }

    for path in paths.values():
        if not os.path.isfile(path):
            die("missing {}".format(path))

    text = dict((name, read_text(path)) for name, path in paths.items())

    if MARKER in text["afp_h"]:
        print("AFP 2.x date normalization already applied: {}".format(root))
        return

    # include/afp.h: retain the offset sampled from FPGetSrvrParms.
    old = """    /* This is the time we connected */
    time_t connect_time;

    /* UAMs */
"""
    new = """    /* This is the time we connected */
    time_t connect_time;

    /* GLOBALTALK AFP2 DATE NORMALIZATION R1
     * AFP 2.x timestamps use the server's local clock.  This is the
     * server-minus-client offset calculated from FPGetSrvrParms. */
    time_t time_offset;

    /* UAMs */
"""
    text["afp_h"] = replace_once(
        text["afp_h"], old, new, "include/afp.h time_offset")

    # lib/afp_internal.h: expose signed AFP-date converters to all protocol
    # decoders/encoders while retaining the old macros for untouched code.
    old = """#define AD_DATE_DELTA         946684800
#define AD_DATE_FROM_UNIX(x)  (htonl((x) - AD_DATE_DELTA))
#define AD_DATE_TO_UNIX(x)    (ntohl(x) + AD_DATE_DELTA)

void add_file_by_name(struct afp_file_info ** base, const char *filename);
"""
    new = """#define AD_DATE_DELTA         946684800LL
#define AD_DATE_FROM_UNIX(x)  (htonl((x) - AD_DATE_DELTA))
#define AD_DATE_TO_UNIX(x)    (ntohl(x) + AD_DATE_DELTA)

/* AFP dates are signed, network-order, seconds from 2000-01-01. */
time_t afp_date_to_unix(const struct afp_server *server, uint32_t date);
uint32_t afp_date_from_unix(const struct afp_server *server, time_t date);

void add_file_by_name(struct afp_file_info ** base, const char *filename);
"""
    text["internal"] = replace_once(
        text["internal"], old, new, "lib/afp_internal.h date helpers")

    # lib/proto_server.c: signed conversion plus AFP 2.x server clock offset.
    old = """#include <stdlib.h>
#include <string.h>
"""
    new = """#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
"""
    text["server"] = replace_once(
        text["server"], old, new, "lib/proto_server.c includes")

    anchor = """int afp_getsrvrparms(struct afp_server *server)
{
"""
    helper = r'''static int server_uses_local_time(const struct afp_server *server)
{
    return server && server->using_version
           && server->using_version->av_number < 30;
}

time_t afp_date_to_unix(const struct afp_server *server, uint32_t date)
{
    uint32_t wire_seconds = ntohl(date);
    int64_t seconds = wire_seconds;

    /* AFP defines this field as a signed long.  Sign-extend before applying
     * the 2000 epoch; 0x80000000 is the protocol's unset-date sentinel. */
    if (wire_seconds & UINT32_C(0x80000000)) {
        seconds -= INT64_C(0x100000000);
    }

    seconds += AD_DATE_DELTA;

    if (server_uses_local_time(server)) {
        seconds -= server->time_offset;
    }

    return (time_t)seconds;
}

uint32_t afp_date_from_unix(const struct afp_server *server, time_t date)
{
    int64_t seconds = (int64_t)date - AD_DATE_DELTA;

    if (server_uses_local_time(server)) {
        seconds += server->time_offset;
    }

    return htonl((uint32_t)seconds);
}

'''
    text["server"] = replace_once(
        text["server"], anchor, helper + anchor,
        "lib/proto_server.c date helper insertion")

    old = """    server->connect_time = AD_DATE_TO_UNIX(afp_getsrvparm_reply->time);
    server->num_volumes = afp_getsrvparm_reply->numvolumes;
"""
    new = """    server->connect_time = afp_date_to_unix(
                               NULL, afp_getsrvparm_reply->time);

    if (server_uses_local_time(server)) {
        /* AFP 2.x dates use the server's local clock.  Express subsequent
         * dates on the client's Unix time base, using the server time sampled
         * in this reply.  This intentionally also corrects a badly wrong
         * classic server clock; the offset is not merely a timezone delta. */
        server->time_offset = server->connect_time - time(NULL);
        server->connect_time -= server->time_offset;
    }

    server->num_volumes = afp_getsrvparm_reply->numvolumes;
"""
    text["server"] = replace_once(
        text["server"], old, new,
        "lib/proto_server.c FPGetSrvrParms normalization")

    # File/directory and volume reply decoders all need the same server-aware
    # conversion.  This is the read path used by stat/list/download.
    text["reply"] = replace_count(
        text["reply"],
        "AD_DATE_TO_UNIX(*date)",
        "afp_date_to_unix(server, *date)",
        3,
        "lib/proto_replyblock.c date reads")

    text["volume"] = replace_count(
        text["volume"],
        "AD_DATE_TO_UNIX(*date)",
        "afp_date_to_unix(server, *date)",
        3,
        "lib/proto_volume.c date reads")

    # Keep the inverse conversion symmetric for upload/set-date paths.
    replacements = (
        ("AD_DATE_FROM_UNIX(fp->creation_date)",
         "afp_date_from_unix(server, fp->creation_date)", "create"),
        ("AD_DATE_FROM_UNIX(fp->modification_date)",
         "afp_date_from_unix(server, fp->modification_date)", "modify"),
        ("AD_DATE_FROM_UNIX(fp->backup_date)",
         "afp_date_from_unix(server, fp->backup_date)", "backup"),
    )

    for old, new, label in replacements:
        text["files"] = replace_once(
            text["files"], old, new,
            "lib/proto_files.c {} date write".format(label))

    # Transactional at the patcher level: write only after every guard above
    # succeeded, avoiding a half-applied generated work tree.
    for name, path in paths.items():
        write_text(path, text[name])

    print("Applied AFP 2.x date normalization R1: {}".format(root))
    print("  FPGetSrvrParms establishes server-minus-client clock offset")
    print("  AFP 2.x file/directory dates are normalized on read")
    print("  AFP 2.x set-date values apply the inverse offset on write")
    print("  signed pre-2000 AFP date values are preserved")
    print("  DDP/ATP/ASP transport is unchanged")


if __name__ == "__main__":
    main()
