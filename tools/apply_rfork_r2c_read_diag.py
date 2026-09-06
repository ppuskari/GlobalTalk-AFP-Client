#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2C diagnostic overlay for ll_read().
# Written for Debian Jessie / Python 3.4 compatibility.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "lowlevel.c")
MARKER = "GLOBALTALK RFORK R2C READ DIAG"


def die(msg):
    raise SystemExit("apply_rfork_r2c_read_diag: " + msg)


if not os.path.isfile(PATH):
    die("lowlevel.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R2C read diagnostics already applied: {}".format(PATH))
    raise SystemExit(0)

old = """        if (volume->server->using_version->av_number < 30) {\n            if (read_offset > UINT32_MAX) {\n                ret = EFBIG;\n                goto error;\n            }\n\n            rc = afp_read(volume, fp->forkid, (uint32_t)read_offset,\n                          (uint32_t)chunksize, &buffer);\n        } else {\n            rc = afp_readext(volume, fp->forkid, read_offset,\n                             (uint64_t)chunksize, &buffer);\n        }\n\n        switch (rc) {\n"""

new = """        fprintf(stderr,\n                \"R2C READ before resource=%u fork=%u off=%llu ask=%zu rxq=%u afpver=%u\\n\",\n                (unsigned int)fp->resource,\n                (unsigned int)fp->forkid,\n                (unsigned long long)read_offset,\n                chunksize,\n                rx_quantum,\n                (unsigned int)volume->server->using_version->av_number);\n\n        if (volume->server->using_version->av_number < 30) {\n            if (read_offset > UINT32_MAX) {\n                ret = EFBIG;\n                goto error;\n            }\n\n            rc = afp_read(volume, fp->forkid, (uint32_t)read_offset,\n                          (uint32_t)chunksize, &buffer);\n        } else {\n            rc = afp_readext(volume, fp->forkid, read_offset,\n                             (uint64_t)chunksize, &buffer);\n        }\n\n        fprintf(stderr,\n                \"R2C READ after rc=%d rc_hex=0x%08x size=%u max=%u err=%d err_hex=0x%08x\\n\",\n                rc, (unsigned int)rc,\n                buffer.size, buffer.maxsize,\n                buffer.errorcode, (unsigned int)buffer.errorcode);\n        /* GLOBALTALK RFORK R2C READ DIAG */\n\n        switch (rc) {\n"""

count = text.count(old)
if count != 1:
    die("ll_read AFP call guard expected once, found {}".format(count))

text = text.replace(old, new, 1)

old = """    if (ll_handle_unlocking(volume, fp->forkid, offset, size)) {\n        /* Somehow, we couldn't unlock the range. */\n        ret = EIO;\n        goto error;\n    }\n\n    return (int)totalsize;\n"""

new = """    {\n        int unlock_rc = ll_handle_unlocking(volume, fp->forkid, offset, size);\n        fprintf(stderr,\n                \"R2C READ unlock rc=%d fork=%u off=%lld size=%zu total=%zu\\n\",\n                unlock_rc, (unsigned int)fp->forkid,\n                (long long)offset, size, totalsize);\n        if (unlock_rc) {\n            /* Somehow, we couldn't unlock the range. */\n            ret = EIO;\n            goto error;\n        }\n    }\n\n    return (int)totalsize;\n"""

count = text.count(old)
if count != 1:
    die("ll_read unlock guard expected once, found {}".format(count))
text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2C ll_read diagnostics: {}".format(PATH))
