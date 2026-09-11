#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7A: Finder-compatible ATP retry budget.
#
# A System 7.6 Finder reference capture against the LisaGaming Performa 475
# showed a successful AFP FPRead transaction that required the initial ATP
# TREQ plus five timeout retransmissions, all with the same TID and selective
# missing-response bitmap.  Netatalk/libatalk interprets atp_sreqtries as the
# total number of sends (it subtracts the already-sent initial request), while
# the existing ASP adapter requested only five total sends.
#
# Keep the proven 2-second timer, selective bitmap, TID handling, ATP response
# count, ASP sequencing, and all R6.x recovery logic unchanged.  Increase only
# ordinary ASP command/write transactions from five to six total sends.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK FINDER ATP RETRY R7A"


def die(msg):
    raise SystemExit("apply_finder_atp_retry_r7a: " + msg)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_finder_atp_retry_r7a.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "lib", "asp_transport.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if MARKER in text:
        print("Finder ATP retry R7A already applied: {}".format(path))
        return

    old = ("    atpb.atp_sreqto = 2;\n"
           "    atpb.atp_sreqtries = 5;\n")
    count = text.count(old)
    if count != 2:
        die("expected two ASP 2s/5-send request sites, found {}".format(count))

    new = ("    atpb.atp_sreqto = 2;\n"
           "    /* GLOBALTALK FINDER ATP RETRY R7A\n"
           "     * System 7.6 Finder was captured succeeding after five\n"
           "     * timeout retransmissions.  libatalk counts the initial\n"
           "     * send in atp_sreqtries, so six means initial + five. */\n"
           "    atpb.atp_sreqtries = 6;\n")

    text = text.replace(old, new)

    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)

    print("Applied Finder ATP retry R7A: {}".format(path))
    print("  ASP retry timer: unchanged at 2 seconds")
    print("  ordinary ASP command/write sends: 5 -> 6 total")
    print("  selective missing-packet bitmap: unchanged")
    print("  ATP TID and XO/TREL behavior: unchanged")
    print("  ATP response ceiling: unchanged")
    print("  R6.x recovery layers: unchanged")


if __name__ == "__main__":
    main()
