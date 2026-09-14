#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R7S UI layer.  Reuse the proven PuTTY/UTF-8 transforms from R7Q, then make
# the meter aware of durable cross-process offsets and R7S recovery events.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(ROOT, "scripts", "gt-pull-stable-putty.py")

if not os.path.isfile(BASE):
    print("R7S base PuTTY shim missing: %s" % BASE, file=sys.stderr)
    sys.exit(1)

# Jessie commonly runs this project with an ASCII locale.  The parent shim
# intentionally contains classic-Mac examples such as ƒ, so never let Python
# 3.4 choose the process locale for decoding our own UTF-8 source files.
with io.open(BASE, "r", encoding="utf-8") as handle:
    shim = handle.read()

anchor = 'code = compile(source, IMPL, "exec")\n'
if anchor not in shim:
    print("R7S UI: base compile anchor missing; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)

inject = r"""
# GLOBALTALK LOCALTALK ENDURANCE R7S - presentation/accounting layer.
# A resumed file's R7P total includes bytes committed by a previous process,
# while R7P delta contains only bytes delivered during this process.  Keep
# those two concepts separate so payload rate is not inflated by resume.

old = 'IMPORTANT = (\n    "R7I:",'
new = 'IMPORTANT = (\n    "R7S:", "R7I:",'
if old not in source:
    print("R7S UI: IMPORTANT guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

source = source.replace(
    'print("GlobalTalk AFP Client Stable R7Q")',
    'print("GlobalTalk AFP Client Stable R7S - LocalTalk Endurance")', 1)
source = source.replace(
    'print("  retry:     same size+mtime reuses data; metadata is refreshed")',
    'print("  retry:     CNID+size checkpoints; failed files deferred up to 5 fresh passes")',
    1)
source = source.replace(
    'print("  meter:     actual AFP payload + logical whole-tree completion")',
    'print("  meter:     actual AFP payload + logical whole-tree completion")\n'
    '    print("  state:     %s" % env.get("GT_AFP_R7S_STATE_DIR", "disabled"))',
    1)
source = source.replace(
    'logfile.write("Stable R7Q retry-safe pull\\n")',
    'logfile.write("Stable R7S LocalTalk endurance pull\\n")', 1)

old = '''        "data": 0,\n        "logical_data": int(expected_data) if skipped else 0,\n'''
new = '''        "data": 0,\n        "payload_data": 0,\n        "logical_data": int(expected_data) if skipped else 0,\n'''
if old not in source:
    print("R7S UI: current-data guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

old = '    totals["payload_data"] += current["data"]\n'
new = '    totals["payload_data"] += current["payload_data"]\n'
if old not in source:
    print("R7S UI: finalize payload guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

old = '''                        kind, path, delta, total, expected = progress.groups()\n                        del delta\n                        total = int(total)\n'''
new = '''                        kind, path, delta, total, expected = progress.groups()\n                        delta = int(delta)\n                        total = int(total)\n'''
if old not in source:
    print("R7S UI: R7P delta parse guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

old = '''                        if kind == "data":\n                            current["data"] = max(current["data"], total)\n'''
new = '''                        if kind == "data":\n                            current["payload_data"] += delta\n                            current["data"] = max(current["data"], total)\n'''
if old not in source:
    print("R7S UI: data accounting guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

old = '''                    cur_data = current["data"] if current else 0\n                    cur_logical = current["logical_data"] if current else 0\n'''
new = '''                    cur_data = current["data"] if current else 0\n                    cur_payload_data = current["payload_data"] if current else 0\n                    cur_logical = current["logical_data"] if current else 0\n'''
if old not in source:
    print("R7S UI: live payload local guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

old = '''                    payload = (totals["payload_data"] + cur_data +\n                               totals["resource"] + cur_resource)\n'''
new = '''                    payload = (totals["payload_data"] + cur_payload_data +\n                               totals["resource"] + cur_resource)\n'''
if old not in source:
    print("R7S UI: live payload formula guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old, new, 1)

"""

shim = shim.replace(anchor, inject + anchor, 1)
code = compile(shim, BASE, "exec")
exec(code, {"__name__": "__main__", "__file__": BASE, "__package__": None})
