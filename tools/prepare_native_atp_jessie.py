#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Prepare the native ATP R1 source for the historical libatalk development
# headers installed on the Debian Jessie A2SERVER host. The installed atp.h
# predates ATP_MAXRESP and can mention struct at_addr without defining the tag
# before the atp_open prototype. Keep the tracked native source portable; emit
# a build-only copy matched to the installed headers.

from __future__ import print_function

import io
import os
import re
import sys


def die(msg):
    raise SystemExit("prepare_native_atp_jessie: " + msg)


if len(sys.argv) != 3:
    die("usage: prepare_native_atp_jessie.py SOURCE OUTPUT")

src = os.path.abspath(sys.argv[1])
out = os.path.abspath(sys.argv[2])
header = "/usr/local/include/atalk/atp.h"

if not os.path.exists(src):
    die("missing source: {}".format(src))
if not os.path.exists(header):
    die("missing installed libatalk header: {}".format(header))

with io.open(src, "r", encoding="utf-8") as f:
    text = f.read()
with io.open(header, "r", encoding="utf-8", errors="replace") as f:
    atp_h = f.read()

include_old = '''#include <netatalk/at.h>\n#include <atalk/atp.h>\n#include <atalk/ddp.h>\n#include <atalk/netddp.h>\n'''
include_new = '''#include <netatalk/at.h>\n/* Jessie atp.h may introduce struct at_addr only in the atp_open parameter\n * list. Forward-declare the tag first so the header declaration and our\n * definition refer to the same C type. */\nstruct at_addr;\n#include <atalk/ddp.h>\n#include <atalk/atp.h>\n#include <atalk/netddp.h>\n'''

if text.count(include_old) != 1:
    die("native ATP include guard changed")
text = text.replace(include_old, include_new, 1)

marker = '#define GT_QUEUE_MAX 8\n'
replacement = '#define GT_QUEUE_MAX 8\n#define GT_ATP_RESP_MAX 8\n'
if text.count(marker) != 1:
    die("native ATP constant guard changed")
text = text.replace(marker, replacement, 1)

# Some old libatalk headers expose the eight response slots directly in the
# structure but do not publish ATP_MAXRESP as a macro.
text = text.replace("ATP_MAXRESP", "GT_ATP_RESP_MAX")

sig_old = "ATP atp_open(uint8_t port, const struct at_addr *saddr)"
if text.count(sig_old) != 1:
    die("native ATP atp_open signature guard changed")

# Match the exact const-qualification exported by the installed header. Both
# historical forms have existed; using the installed declaration prevents a
# false conflicting-types error on old development packages.
proto = re.search(
    r"atp_open\s*\(\s*u?_?int8_t\s*,\s*(const\s+)?struct\s+at_addr\s*\*",
    atp_h,
    re.MULTILINE,
)
if proto is None:
    # Jessie commonly spells the first type u_int8_t; allow arbitrary spacing
    # and line wrapping while still requiring the at_addr argument.
    proto = re.search(
        r"atp_open\s*\([^,]+,\s*(const\s+)?struct\s+at_addr\s*\*",
        atp_h,
        re.MULTILINE,
    )
if proto is None:
    die("could not determine installed atp_open prototype")

const_kw = "const " if proto.group(1) else ""
sig_new = "ATP atp_open(u_int8_t port, {}struct at_addr *saddr)".format(
    const_kw)
text = text.replace(sig_old, sig_new, 1)

# On this old header set struct at_addr may remain incomplete in the client
# translation unit. We only need its bytes to initialize sockaddr_at.sat_addr,
# so size the copy from the complete destination member instead of dereferencing
# the incomplete source type.
copy_old = "memcpy(&addr.sat_addr, saddr, sizeof(*saddr));"
copy_new = "memcpy(&addr.sat_addr, saddr, sizeof(addr.sat_addr));"
if text.count(copy_old) != 1:
    die("native ATP at_addr copy guard changed")
text = text.replace(copy_old, copy_new, 1)

with io.open(out, "w", encoding="utf-8") as f:
    f.write(text)

print("Prepared Jessie native ATP source: {}".format(out))
print("Installed atp_open const qualifier: {}".format(
    "yes" if const_kw else "no"))
print("ATP response slots: {}".format(8))
print("Jessie struct at_addr forward declaration: enabled")
