#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2F correctness patch for Netatalk Client 0.9.5 ll_open().
#
# The AFP 2.x pre-open FPGetFileDirParms reply parser clears the complete
# afp_file_info result structure.  In the pinned 0.9.5 source that also clears
# fp->resource, so the following FPOpenFork silently opens the data fork even
# when the caller requested the resource fork.
#
# Current Netatalk Client fixes this by preserving the caller's fork type in a
# local variable, restoring fp->resource after the parameter query, and using
# the saved value for the actual fork open/truncate decisions.  Apply that
# upstream-proven correction to the pinned 0.9.5 tree.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "lowlevel.c")
MARKER = "GLOBALTALK RFORK R2F FORKSTATE"


def die(msg):
    raise SystemExit("apply_rfork_r2f_forkstate: " + msg)


if not os.path.isfile(PATH):
    die("lowlevel.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R2F fork-state fix already applied: {}".format(PATH))
    raise SystemExit(0)

old = """    int ret;\n    int dsi_ret;\n    int rc;\n    unsigned char aflags = 0;\n"""
new = """    int ret;\n    int dsi_ret;\n    int rc;\n    unsigned int resource = fp->resource;\n    unsigned char aflags = 0;\n"""
if text.count(old) != 1:
    die("ll_open declaration guard missing/non-unique")
text = text.replace(old, new, 1)

old = """    /*this will be used later for caching*/\n    fp->sync = (unsigned char)(flags & (O_SYNC));\n    fp->writable = (aflags & AFP_OPENFORK_ALLOWWRITE) ? 1 : 0;\n    fp->dirty = 0;\n\n    /* Handle file creation properly when O_CREAT is set */\n"""
new = """    /* Handle file creation properly when O_CREAT is set */\n"""
if text.count(old) != 1:
    die("pre-query client-state guard missing/non-unique")
text = text.replace(old, new, 1)

old = """                                       kFPParentDirIDBit | kFPNodeIDBit |\n                                       (fp->resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),\n                                       0, fp)) {\n"""
new = """                                       kFPParentDirIDBit | kFPNodeIDBit |\n                                       (resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),\n                                       0, fp)) {\n"""
if text.count(old) != 1:
    die("AFP2 fork-length bitmap guard missing/non-unique")
text = text.replace(old, new, 1)

old = """        if ((fp->resource ? (fp->resourcesize >= (AFP_MAX_AFP2_FILESIZE - 1)) :\n                (fp->size >= AFP_MAX_AFP2_FILESIZE - 1))) {\n"""
new = """        if ((resource ? (fp->resourcesize >= (AFP_MAX_AFP2_FILESIZE - 1)) :\n                (fp->size >= AFP_MAX_AFP2_FILESIZE - 1))) {\n"""
if text.count(old) != 1:
    die("AFP2 overflow guard missing/non-unique")
text = text.replace(old, new, 1)

old = """            ret = EOVERFLOW;\n            goto error;\n        }\n    }\n\n    dsi_ret = afp_openfork(volume, fp->resource ? 1 : 0, fp->did,\n                           aflags, fp->basename, fp);\n"""
new = """            ret = EOVERFLOW;\n            goto error;\n        }\n\n        /* GLOBALTALK RFORK R2F FORKSTATE\n         * parse_reply_block() clears the complete result structure.  Keep\n         * the caller's fork type: resource forks need it for both FPOpenFork\n         * and appledouble_close().\n         */\n        fp->resource = resource;\n    }\n\n    /* These are client-side open state, not AFP reply parameters.  Set them\n     * after the AFP 2.x parameter query, whose reply parser clears fp.\n     */\n    fp->sync = (unsigned char)(flags & O_SYNC);\n    fp->writable = (aflags & AFP_OPENFORK_ALLOWWRITE) ? 1 : 0;\n    fp->dirty = 0;\n\n    dsi_ret = afp_openfork(volume, resource ? 1 : 0, fp->did,\n                           aflags, fp->basename, fp);\n"""
if text.count(old) != 1:
    die("post-query FPOpenFork guard missing/non-unique")
text = text.replace(old, new, 1)

old = """        ret = ll_zero_file(volume, fp->forkid, fp->resource);\n"""
new = """        ret = ll_zero_file(volume, fp->forkid, resource);\n"""
if text.count(old) != 1:
    die("truncate fork-type guard missing/non-unique")
text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2F AFP2 fork-state fix: {}".format(PATH))
