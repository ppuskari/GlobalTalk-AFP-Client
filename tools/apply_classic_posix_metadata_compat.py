#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Classic AFP/AppleTalk servers commonly do not implement the Unix privilege
# and timestamp calls used only to mirror local POSIX metadata after the
# Macintosh metadata has been copied. The stateless daemon historically
# translated -ENOSYS/-ENOTSUP from those midlevel calls into a generic daemon
# error, preventing cmdline_afp.c from treating them as optional capabilities.
# Preserve the real NOTSUPPORTED result so FinderInfo/resource-fork transfers
# are not failed merely because chmod/utime are unavailable.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "daemon", "commands.c")
MARKER = "GLOBALTALK CLASSIC POSIX METADATA COMPAT R1"


def die(msg):
    raise SystemExit("apply_classic_posix_metadata_compat: " + msg)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


if not os.path.exists(PATH):
    die("missing {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("Classic POSIX metadata compatibility already applied: {}".format(UP))
    raise SystemExit(0)

chmod_old = '''        if (ret == -ENOENT) {
            result = AFP_SERVER_RESULT_ENOENT;
        } else if (ret == -EACCES || ret == -EPERM) {
            result = AFP_SERVER_RESULT_ACCESS;
        } else {
            result = AFP_SERVER_RESULT_ERROR;
        }

        log_for_client((void *) c, AFPFSD, LOG_ERR,
                       "Failed to chmod file %s: %d (%s)", request->path, ret,
                       strerror(-ret));
'''

chmod_new = '''        /* GLOBALTALK CLASSIC POSIX METADATA COMPAT R1 */
        if (ret == -ENOENT) {
            result = AFP_SERVER_RESULT_ENOENT;
        } else if (ret == -EACCES || ret == -EPERM) {
            result = AFP_SERVER_RESULT_ACCESS;
        } else if (ret == -ENOSYS || ret == -ENOTSUP
                   || ret == -EOPNOTSUPP) {
            result = AFP_SERVER_RESULT_NOTSUPPORTED;
        } else {
            result = AFP_SERVER_RESULT_ERROR;
        }

        log_for_client((void *) c, AFPFSD,
                       (ret == -ENOSYS || ret == -ENOTSUP
                        || ret == -EOPNOTSUPP) ? LOG_DEBUG : LOG_ERR,
                       "Failed to chmod file %s: %d (%s)", request->path, ret,
                       strerror(-ret));
'''

text = replace_once(text, chmod_old, chmod_new, "process_chmod mapping")

utime_old = '''        if (ret == -ENOENT) {
            result = AFP_SERVER_RESULT_ENOENT;
        } else if (ret == -EACCES) {
            result = AFP_SERVER_RESULT_ACCESS;
        } else {
            result = AFP_SERVER_RESULT_ERROR;
        }

        log_for_client((void *) c, AFPFSD, LOG_ERR, "Failed to utime file %s: %d",
                       request->path, ret);
'''

utime_new = '''        if (ret == -ENOENT) {
            result = AFP_SERVER_RESULT_ENOENT;
        } else if (ret == -EACCES || ret == -EPERM) {
            result = AFP_SERVER_RESULT_ACCESS;
        } else if (ret == -ENOSYS || ret == -ENOTSUP
                   || ret == -EOPNOTSUPP) {
            result = AFP_SERVER_RESULT_NOTSUPPORTED;
        } else {
            result = AFP_SERVER_RESULT_ERROR;
        }

        log_for_client((void *) c, AFPFSD,
                       (ret == -ENOSYS || ret == -ENOTSUP
                        || ret == -EOPNOTSUPP) ? LOG_DEBUG : LOG_ERR,
                       "Failed to utime file %s: %d", request->path, ret);
'''

text = replace_once(text, utime_old, utime_new, "process_utime mapping")

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied classic POSIX metadata compatibility: {}".format(UP))
