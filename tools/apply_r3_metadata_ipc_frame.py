#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R3 raised AFP_SL_METADATA_CHUNK from 4096 to 16384 bytes.  Reads remained
# safe because the large payload travels in the daemon response, but metadata
# writes place that payload after struct afp_server_metadata_request in the
# client->afpsld request.  Netatalk Client 0.9.5's daemon_client.h only allows
# an 8192-byte incoming command frame, so a 16 KiB resource-fork write is
# rejected before process_metadata() can see it and the client reports
# ECONNRESET.
#
# Give the stateless daemon enough framing room for the 16 KiB R3 payload plus
# path/name/request fields.  32 KiB is deliberately bounded and leaves ample
# slack without changing AFP/ASP/DDP wire sizes.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "daemon", "daemon_client.h")
MARKER = "GLOBALTALK R3 32K STATELESS METADATA IPC FRAME"


def die(msg):
    raise SystemExit("apply_r3_metadata_ipc_frame: " + msg)


if not os.path.isfile(PATH):
    die("daemon_client.h not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R3 metadata IPC frame already applied: {}".format(PATH))
    raise SystemExit(0)

old = "#define AFP_CLIENT_INCOMING_BUF 8192\n"
new = """/* GLOBALTALK R3 32K STATELESS METADATA IPC FRAME\n * R3 metadata writes can carry a 16384-byte payload plus the stateless\n * metadata request header/path/name fields.  The original 8192-byte command\n * frame was therefore smaller than a valid R3 write request.\n */\n#define AFP_CLIENT_INCOMING_BUF 32768\n"""

if text.count(old) != 1:
    die("AFP_CLIENT_INCOMING_BUF guard missing/non-unique")

text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R3 32 KiB stateless metadata IPC frame: {}".format(PATH))
