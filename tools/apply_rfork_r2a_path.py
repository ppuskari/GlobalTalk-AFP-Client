#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# R2A hardware-test compatibility patch.
#
# The pre-R2 Jessie tree that successfully resolves Classic AFP paths stores
# url->path with the leading '/'.  Clean R2 accidentally regressed to a
# relative path, which causes the stateless helper to fail pathname traversal
# after the volume is opened.  Restore only that proven behavior here so the
# resource-fork R2 changes can be tested independently.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "afp_url.c")

OLD = """    if (slash && slash[1]) {\n        strlcpy(url->path, slash + 1,\n                sizeof(url->path));\n    }\n"""

NEW = """    if (slash && slash[1]) {\n        url->path[0] = '/';\n        strlcpy(url->path + 1, slash + 1,\n                sizeof(url->path) - 1);\n    }\n"""


def die(msg):
    raise SystemExit("apply_rfork_r2a_path: " + msg)


if not os.path.isfile(PATH):
    die("Netatalk Client afp_url.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if NEW in text:
    print("R2A rooted DDP path already applied: {}".format(PATH))
    raise SystemExit(0)

count = text.count(OLD)
if count != 1:
    die("expected DDP path guard once, found {}".format(count))

text = text.replace(OLD, NEW, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied R2A rooted DDP path fix: {}".format(PATH))
