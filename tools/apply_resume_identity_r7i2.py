#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7I.2: strict same-object resume validation.
#
# Recursive FPEnumerate already returns file_id (AFP NodeID/CNID), but the
# stock cmdline recursive downloader only copies mode/size/uid/gid/mtime into
# the synthetic struct stat passed to retrieve_file().  Carry file_id in
# st_ino, require nonzero matching CNIDs plus exact size across reconnect, and
# clean up the close-only recovery case where all data bytes are already local.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RESUME IDENTITY R7I.2"


def die(msg):
    raise SystemExit("apply_resume_identity_r7i2: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_resume_identity_r7i2.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Resume identity R7I.2 already applied: {}".format(path))
        return
    if "GLOBALTALK RESUME IDENTITY R7I.1" not in text:
        die("R7I.1 must be applied first")

    # Preserve AFP file NodeID/CNID from FPEnumerate in the synthetic stat.
    old_stat = '''            st.st_mode = p->unixprivs.permissions;\n            st.st_size = p->size;\n            st.st_uid = p->unixprivs.uid;\n'''
    new_stat = '''            st.st_mode = p->unixprivs.permissions;\n            st.st_size = p->size;\n            /* GLOBALTALK RESUME IDENTITY R7I.2\n             * Netatalk maps AFP NodeID/CNID to st_ino for normal stat calls.\n             * Preserve the FPEnumerate file_id the same way so reconnect\n             * validation can prove this is the same namespace object. */\n            st.st_ino = p->file_id;\n            st.st_uid = p->unixprivs.uid;\n'''
    text = replace_once(text, old_stat, new_stat,
                        "recursive FPEnumerate CNID propagation")

    old_check = '''        if (fresh_stat.st_size != expected_stat.st_size\n                || (expected_stat.st_ino != 0 && fresh_stat.st_ino != 0\n                    && fresh_stat.st_ino != expected_stat.st_ino)) {\n            printf("R7I: resume identity mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-cnid=%llu fresh-cnid=%llu\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (unsigned long long)expected_stat.st_ino,\n                   (unsigned long long)fresh_stat.st_ino);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n'''
    new_check = '''        /* GLOBALTALK RESUME IDENTITY R7I.2\n         * Resume is allowed only when both namespace identities are usable\n         * and equal, and the data-fork size is still exact.  Never silently\n         * fall back to pathname+size when CNID is unavailable. */\n        if (expected_stat.st_ino == 0 || fresh_stat.st_ino == 0\n                || fresh_stat.st_ino != expected_stat.st_ino\n                || fresh_stat.st_size != expected_stat.st_size) {\n            printf("R7I.2: resume identity mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-cnid=%llu fresh-cnid=%llu\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (unsigned long long)expected_stat.st_ino,\n                   (unsigned long long)fresh_stat.st_ino);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n'''
    text = replace_once(text, old_check, new_check,
                        "strict CNID/size resume validation")

    old_retry = '''    if (recoveries > 0) {\n        printf("R7I: resuming current file path=%s offset=%llu recovery=%d/%d\\n",\n               path, offset, recoveries, max_recoveries);\n    }\n\n    if ((unsigned long long)expected_stat.st_size == total) {\n        goto complete_file;\n    }\n'''
    new_retry = '''    if ((unsigned long long)expected_stat.st_size == total) {\n        if (recoveries > 0) {\n            printf("R7I.2: data already complete after recovery; "\n                   "no fork reopen required path=%s bytes=%llu recovery=%d/%d\\n",\n                   path, total, recoveries, max_recoveries);\n        }\n        goto complete_file;\n    }\n\n    if (recoveries > 0) {\n        printf("R7I: resuming current file path=%s offset=%llu recovery=%d/%d\\n",\n               path, offset, recoveries, max_recoveries);\n    }\n'''
    text = replace_once(text, old_retry, new_retry,
                        "completed-data close recovery")

    write_text(path, text)
    print("Applied resume identity R7I.2: {}".format(path))
    print("  recursive FPEnumerate file_id now propagates to stat.st_ino")
    print("  resume requires nonzero matching AFP CNID + exact fork size")
    print("  zero/unavailable CNID refuses offset resume")
    print("  completed-data close recovery no longer pretends to reopen/resume")
    print("  mtime drift remains diagnostic only")


if __name__ == "__main__":
    main()
