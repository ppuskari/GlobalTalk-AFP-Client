#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2E diagnostic overlay for ll_open().
# Logs the AFP 2.x pre-open file-parameter query and FPOpenFork result into the
# same GT_R2_READ_LOG file used by R2D.  Written for Debian Jessie/Python 3.4.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "lowlevel.c")
MARKER = "GLOBALTALK RFORK R2E OPEN DIAG"


def die(msg):
    raise SystemExit("apply_rfork_r2e_open_diag: " + msg)


if not os.path.isfile(PATH):
    die("lowlevel.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R2E fork-open diagnostics already applied: {}".format(PATH))
    raise SystemExit(0)

if "GLOBALTALK RFORK R2D DAEMON LOG" not in text:
    die("R2D daemon logging must be applied first")

old = """        switch (ll_get_directory_entry(volume, fp->basename, fp->did,\n                                       kFPParentDirIDBit | kFPNodeIDBit |\n                                       (fp->resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),\n                                       0, fp)) {\n"""
new = """        rc = ll_get_directory_entry(volume, fp->basename, fp->did,\n                                    kFPParentDirIDBit | kFPNodeIDBit |\n                                    (fp->resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),\n                                    0, fp);\n        gt_r2d_read_log(\n                \"R2E OPEN preget resource=%u did=%u name=%s rc=%d rc_hex=0x%08x data=%llu rsrc=%llu\\n\",\n                (unsigned int)fp->resource,\n                fp->did, fp->basename,\n                rc, (unsigned int)rc,\n                (unsigned long long)fp->size,\n                (unsigned long long)fp->resourcesize);\n        /* GLOBALTALK RFORK R2E OPEN DIAG */\n        switch (rc) {\n"""
count = text.count(old)
if count != 1:
    die("AFP2 pre-open query guard expected once, found {}".format(count))
text = text.replace(old, new, 1)

old = """    dsi_ret = afp_openfork(volume, fp->resource ? 1 : 0, fp->did,\n                           aflags, fp->basename, fp);\n\n    switch (dsi_ret) {\n"""
new = """    gt_r2d_read_log(\n            \"R2E OPEN before resource=%u did=%u name=%s access=0x%02x afpver=%u\\n\",\n            (unsigned int)fp->resource, fp->did, fp->basename,\n            (unsigned int)aflags,\n            (unsigned int)volume->server->using_version->av_number);\n\n    dsi_ret = afp_openfork(volume, fp->resource ? 1 : 0, fp->did,\n                           aflags, fp->basename, fp);\n\n    gt_r2d_read_log(\n            \"R2E OPEN after resource=%u rc=%d rc_hex=0x%08x fork=%u\\n\",\n            (unsigned int)fp->resource,\n            dsi_ret, (unsigned int)dsi_ret,\n            (unsigned int)fp->forkid);\n\n    switch (dsi_ret) {\n"""
count = text.count(old)
if count != 1:
    die("FPOpenFork guard expected once, found {}".format(count))
text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2E ll_open/FPOpenFork diagnostics: {}".format(PATH))
