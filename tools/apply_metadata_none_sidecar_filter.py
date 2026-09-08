#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# In metadata mode "none", recursive uploads should copy only ordinary user
# files.  Netatalk Client 0.9.5 filters .AppleDouble only when the selected
# metadata mode is NETATALK, so a data-only upload of a previously downloaded
# Netatalk tree can accidentally publish .AppleDouble as a normal AFP folder.
# Treat both common sidecar representations as implementation details in NONE
# mode as well.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "cmdline", "cmdline_afp.c")
MARKER = "GLOBALTALK METADATA NONE SIDECAR FILTER R1"


def die(msg):
    raise SystemExit("apply_metadata_none_sidecar_filter: " + msg)


if not os.path.isfile(PATH):
    die("cmdline_afp.c not found: {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("Metadata-none sidecar filter already applied: {}".format(PATH))
    raise SystemExit(0)

old = '''    if (transfer_metadata_mode == AFP_METADATA_NETATALK) {
        return strcmp(name, ".AppleDouble") == 0;
    }

    return 0;
'''
new = '''    if (transfer_metadata_mode == AFP_METADATA_NETATALK) {
        return strcmp(name, ".AppleDouble") == 0;
    }

    /* GLOBALTALK METADATA NONE SIDECAR FILTER R1
     * A data-only upload must not expose metadata implementation files as
     * ordinary AFP content.  Accept either common local sidecar convention. */
    if (transfer_metadata_mode == AFP_METADATA_NONE) {
        return strncmp(name, "._", 2) == 0
               || strcmp(name, ".AppleDouble") == 0;
    }

    return 0;
'''

if text.count(old) != 1:
    die("metadata_sidecar_entry guard missing/non-unique")

text = text.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied metadata-none sidecar filter: {}".format(PATH))
