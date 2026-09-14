#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Stable R7 user entrypoint.  The implementation lives in
# gt-pull-stable-total.py so the browser and direct command keep the original
# stable command name while the whole-tree preflight meter is validated.

from __future__ import print_function

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMPL = os.path.join(ROOT, "scripts", "gt-pull-stable-total.py")

if not os.path.isfile(IMPL):
    print("Stable R7 progress implementation missing: %s" % IMPL,
          file=sys.stderr)
    sys.exit(1)

os.execv(sys.executable, [sys.executable, IMPL] + sys.argv[1:])
