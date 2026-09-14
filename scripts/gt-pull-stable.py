#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Stable R7 user entrypoint.

from __future__ import print_function

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMPL = os.path.join(ROOT, "scripts", "gt-pull-stable-putty.py")

if not os.path.isfile(IMPL):
    print("Stable R7Q PuTTY UI shim missing: %s" % IMPL,
          file=sys.stderr)
    sys.exit(1)

args = list(sys.argv[1:])
recursive = ("-r" in args or "--recursive" in args)
preflight = os.environ.get("GT_AFP_PREFLIGHT", "0").strip().lower()
preflight_enabled = preflight in ("1", "true", "yes", "on")

# The current whole-tree preflight uses one gt-afp-ls process/session per
# directory.  Several classic AFP servers tolerate the real long-lived pull
# but become unable to accept a fresh login after repeated one-shot catalog
# sessions.  Until the catalog walker is converted to a single AFP session,
# recursive pulls therefore default to live-only progress.
if recursive and not preflight_enabled and "--no-preflight" not in args:
    args.insert(0, "--no-preflight")

os.execv(sys.executable, [sys.executable, IMPL] + args)
