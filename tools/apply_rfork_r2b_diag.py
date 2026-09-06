#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2B diagnostic overlay for the remote->local metadata path.
# Written for Debian Jessie / Python 3.4 compatibility.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "daemon", "metadata.c")
MARKER = "GLOBALTALK RFORK R2B META DIAG"


def die(msg):
    raise SystemExit("apply_rfork_r2b_diag: " + msg)


if not os.path.isfile(PATH):
    die("metadata.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("R2B metadata diagnostics already applied: {}".format(PATH))
    raise SystemExit(0)

start = text.find("int afp_sl_metadata_copy_remote_to_local(")
end = text.find("\nint afp_sl_metadata_copy_remote_to_remote(", start)

if start < 0 or end < 0 or end <= start:
    die("could not isolate remote-to-local metadata function")

segment = text[start:end]


def inject_after(old, added, label):
    global segment
    count = segment.count(old)
    if count != 1:
        die("{} guard expected once, found {}".format(label, count))
    segment = segment.replace(old, old + added, 1)


inject_after(
    "    finder_ret = afp_sl_getfinderinfo(source_volume, source_path, finderinfo,\n"
    "                                      sizeof(finderinfo));\n",
    "    fprintf(stderr, \"R2B META finder-get ret=%d remote=%s\\n\",\n"
    "            finder_ret, source_path); /* {} */\n".format(MARKER),
    "finder-get",
)

inject_after(
    "        ret = local_finderinfo_set(local_path, mode, finderinfo);\n",
    "        fprintf(stderr, \"R2B META finder-set ret=%d local=%s\\n\",\n"
    "                ret, local_path);\n",
    "finder-set",
)

inject_after(
    "    ret = afp_sl_getresourcefork(source_volume, source_path, NULL, 0, 0);\n",
    "    fprintf(stderr, \"R2B META rsrc-size ret=%d remote=%s\\n\",\n"
    "            ret, source_path);\n",
    "resource-size",
)

inject_after(
    "            ret = afp_sl_getresourcefork(source_volume, source_path, buffer,\n"
    "                                         chunk, offset);\n",
    "            fprintf(stderr,\n"
    "                    \"R2B META rsrc-read off=%llu ask=%zu ret=%d\\n\",\n"
    "                    offset, chunk, ret);\n",
    "resource-read",
)

inject_after(
    "            int write_ret = local_resourcefork_write(local_path, mode, buffer,\n"
    "                            (size_t)ret, (off_t)offset);\n",
    "            fprintf(stderr,\n"
    "                    \"R2B META rsrc-write off=%llu got=%d ret=%d\\n\",\n"
    "                    offset, ret, write_ret);\n",
    "resource-write",
)

old_tail = (
    "    return transfer_remote_xattrs_to_local(source_volume, source_path,\n"
    "                                           local_path, mode, warnings);\n"
)
new_tail = (
    "    ret = transfer_remote_xattrs_to_local(source_volume, source_path,\n"
    "                                          local_path, mode, warnings);\n"
    "    fprintf(stderr, \"R2B META xattrs ret=%d remote=%s\\n\",\n"
    "            ret, source_path);\n"
    "    return ret;\n"
)
count = segment.count(old_tail)
if count != 1:
    die("xattr tail guard expected once, found {}".format(count))
segment = segment.replace(old_tail, new_tail, 1)

text = text[:start] + segment + text[end:]

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2B metadata diagnostics: {}".format(PATH))
