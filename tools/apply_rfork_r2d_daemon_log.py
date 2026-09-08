#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2D diagnostic overlay.
#
# R2C instruments ll_read(), but ll_read() executes inside afpsld.  afpsld's
# stderr is not the gt-afp-pull stream captured by tee, so persist those lines
# to the path named by GT_R2_READ_LOG instead.  No file is written unless that
# environment variable is set.  Written for Debian Jessie / Python 3.4.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "lowlevel.c")
MARKER = "GLOBALTALK RFORK R2D DAEMON LOG"


def die(msg):
    raise SystemExit("apply_rfork_r2d_daemon_log: " + msg)


if not os.path.isfile(PATH):
    die("lowlevel.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R2D daemon logging already applied: {}".format(PATH))
    raise SystemExit(0)

if "GLOBALTALK RFORK R2C READ DIAG" not in text:
    die("R2C ll_read diagnostics must be applied first")

old = '#include <stdio.h>\n'
new = '#include <stdio.h>\n#include <stdarg.h>\n'
if text.count(old) != 1:
    die("stdio include guard missing/non-unique")
text = text.replace(old, new, 1)

anchor = '#include "forklist.h"\n\n'
helper = r'''#include "forklist.h"

/* GLOBALTALK RFORK R2D DAEMON LOG
 * ll_read() runs in afpsld, whose stderr is not the gt-afp-pull pipe.
 * Persist diagnostics only when the caller explicitly supplies a log path.
 */
static void gt_r2d_read_log(const char *fmt, ...)
{
    const char *path = getenv("GT_R2_READ_LOG");
    FILE *fp;
    va_list ap;

    if (!path || !path[0]) {
        return;
    }

    fp = fopen(path, "a");
    if (!fp) {
        return;
    }

    va_start(ap, fmt);
    vfprintf(fp, fmt, ap);
    va_end(ap);
    fflush(fp);
    fclose(fp);
}

'''
if text.count(anchor) != 1:
    die("forklist include anchor missing/non-unique")
text = text.replace(anchor, helper, 1)

replacements = [
    (
        '''        fprintf(stderr,\n                "R2C READ before resource=%u fork=%u off=%llu ask=%zu rxq=%u afpver=%u\\n",\n                (unsigned int)fp->resource,\n                (unsigned int)fp->forkid,\n                (unsigned long long)read_offset,\n                chunksize,\n                rx_quantum,\n                (unsigned int)volume->server->using_version->av_number);\n''',
        '''        gt_r2d_read_log(\n                "R2D READ before resource=%u fork=%u off=%llu ask=%zu rxq=%u afpver=%u\\n",\n                (unsigned int)fp->resource,\n                (unsigned int)fp->forkid,\n                (unsigned long long)read_offset,\n                chunksize,\n                rx_quantum,\n                (unsigned int)volume->server->using_version->av_number);\n''',
        "before-read",
    ),
    (
        '''        fprintf(stderr,\n                "R2C READ after rc=%d rc_hex=0x%08x size=%u max=%u err=%d err_hex=0x%08x\\n",\n                rc, (unsigned int)rc,\n                buffer.size, buffer.maxsize,\n                buffer.errorcode, (unsigned int)buffer.errorcode);\n''',
        '''        gt_r2d_read_log(\n                "R2D READ after rc=%d rc_hex=0x%08x size=%u max=%u err=%d err_hex=0x%08x\\n",\n                rc, (unsigned int)rc,\n                buffer.size, buffer.maxsize,\n                buffer.errorcode, (unsigned int)buffer.errorcode);\n''',
        "after-read",
    ),
    (
        '''        fprintf(stderr,\n                "R2C READ unlock rc=%d fork=%u off=%lld size=%zu total=%zu\\n",\n                unlock_rc, (unsigned int)fp->forkid,\n                (long long)offset, size, totalsize);\n''',
        '''        gt_r2d_read_log(\n                "R2D READ unlock rc=%d fork=%u off=%lld size=%zu total=%zu\\n",\n                unlock_rc, (unsigned int)fp->forkid,\n                (long long)offset, size, totalsize);\n''',
        "unlock",
    ),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        die("{} diagnostic guard expected once, found {}".format(label, count))
    text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2D daemon-side read logging: {}".format(PATH))
