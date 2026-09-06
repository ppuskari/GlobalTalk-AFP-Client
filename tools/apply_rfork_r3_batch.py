#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Increase the stateless metadata payload from 4 KiB to 16 KiB.
#
# The resource-fork metadata copier calls afp_sl_getresourcefork() once per
# metadata chunk. Each call opens, reads, and closes the remote resource fork.
# With the original 4096-byte chunk this creates a visible 4 KiB staircase and
# repeated AFP open/query/close latency.
#
# Netatalk Client 0.9.5 defines MAX_CLIENT_RESPONSE as 16384 bytes and keeps a
# separate 4096-byte daemon log allowance plus framing slack. Use that exact
# pinned-tag payload ceiling rather than the larger framing used by newer
# Netatalk Client revisions. The AFP/ASP wire transaction remains unchanged at
# 4624 bytes, so a full metadata batch is serviced by four ordinary ASP reads.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "include", "afpsl.h")
MARKER = "GLOBALTALK RFORK R3 16K METADATA BATCH"


def die(msg):
    raise SystemExit("apply_rfork_r3_batch: " + msg)


if not os.path.isfile(PATH):
    die("afpsl.h not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R3 16 KiB metadata batch already applied: {}".format(PATH))
    raise SystemExit(0)

old = """/* Maximum value or resource-fork payload per stateless metadata request. */\n#define AFP_SL_METADATA_CHUNK 4096\n"""
new = """/* Maximum value or resource-fork payload per stateless metadata request.\n * GLOBALTALK RFORK R3 16K METADATA BATCH\n * Netatalk Client 0.9.5 caps MAX_CLIENT_RESPONSE at 16384 bytes. Keep the\n * AFP/ASP wire quantum unchanged; this only batches several AFP reads under\n * one stateless metadata request and one remote fork open.\n */\n#define AFP_SL_METADATA_CHUNK 16384\n"""

if text.count(old) != 1:
    die("metadata chunk guard missing/non-unique")

text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R3 16 KiB metadata batch: {}".format(PATH))
