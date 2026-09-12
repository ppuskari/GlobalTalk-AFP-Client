#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7I.2: strict same-object resume validation.
#
# Netatalk Client 0.9.5 keeps AFP NodeID/CNID in the internal
# struct afp_file_info.fileid, but its stateless afp_file_info_basic and
# readdir wire record omit that field. Extend the private afpsld/libafpsl
# readdir record by one uint32_t so recursive enumeration can carry the real
# CNID into st_ino without adding another AFP request. Then require nonzero
# matching CNID + exact data-fork size before any offset resume.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RESUME IDENTITY R7I.2"
WIRE_MARKER = "GLOBALTALK READDIR CNID WIRE R7I.2"


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
    cmd_path = os.path.join(root, "cmdline", "cmdline_afp.c")
    hdr_path = os.path.join(root, "include", "afpsl.h")
    daemon_path = os.path.join(root, "daemon", "commands.c")
    sl_path = os.path.join(root, "daemon", "stateless.c")

    for path in (cmd_path, hdr_path, daemon_path, sl_path):
        if not os.path.isfile(path):
            die("missing {}".format(path))

    cmd = read_text(cmd_path)
    hdr = read_text(hdr_path)
    daemon = read_text(daemon_path)
    sl = read_text(sl_path)

    fully_applied = (MARKER in cmd and WIRE_MARKER in hdr
                     and WIRE_MARKER in daemon and WIRE_MARKER in sl)
    if fully_applied:
        print("Resume identity R7I.2 already applied: {}".format(root))
        return
    if (MARKER in cmd or WIRE_MARKER in hdr or WIRE_MARKER in daemon
            or WIRE_MARKER in sl):
        die("partial R7I.2 application detected; rebuild from clean generated tree")
    if "GLOBALTALK RESUME IDENTITY R7I.1" not in cmd:
        die("R7I.1 must be applied first")

    # Expose fileid in the stateless public/basic enumeration result.
    old_hdr = '''struct afp_file_info_basic {\n    char name[AFP_MAX_PATH];\n    unsigned int creation_date;\n    unsigned int modification_date;\n    struct afp_unixprivs unixprivs;\n    unsigned long long size;\n};\n'''
    new_hdr = '''struct afp_file_info_basic {\n    char name[AFP_MAX_PATH];\n    unsigned int creation_date;\n    unsigned int modification_date;\n    /* GLOBALTALK READDIR CNID WIRE R7I.2 */\n    unsigned int fileid;\n    struct afp_unixprivs unixprivs;\n    unsigned long long size;\n};\n'''
    hdr = replace_once(hdr, old_hdr, new_hdr,
                       "stateless basic fileid field")

    # afpsld: account for and serialize the internal AFP fileid.
    old_size = '''        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 2 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t);\n'''
    new_size = '''        /* GLOBALTALK READDIR CNID WIRE R7I.2 */\n        size_t entry_size = sizeof(uint32_t) + name_len +\n                            sizeof(uint32_t) * 3 +\n                            sizeof(struct afp_unixprivs) +\n                            sizeof(uint64_t);\n'''
    daemon = replace_once(daemon, old_size, new_size,
                          "readdir packed entry size")

    old_pack = '''        memcpy(p, &fp->modification_date, sizeof(uint32_t));\n        p += sizeof(uint32_t);\n        memcpy(p, &fp->unixprivs, sizeof(struct afp_unixprivs));\n'''
    new_pack = '''        memcpy(p, &fp->modification_date, sizeof(uint32_t));\n        p += sizeof(uint32_t);\n        /* GLOBALTALK READDIR CNID WIRE R7I.2 */\n        memcpy(p, &fp->fileid, sizeof(uint32_t));\n        p += sizeof(uint32_t);\n        memcpy(p, &fp->unixprivs, sizeof(struct afp_unixprivs));\n'''
    daemon = replace_once(daemon, old_pack, new_pack,
                          "readdir fileid serialization")

    # libafpsl: unpack the matching uint32_t into afp_file_info_basic.fileid.
    old_unpack = '''                memcpy(&current_basic->modification_date, p, sizeof(uint32_t));\n                p += sizeof(uint32_t);\n                memcpy(&current_basic->unixprivs, p, sizeof(struct afp_unixprivs));\n'''
    new_unpack = '''                memcpy(&current_basic->modification_date, p, sizeof(uint32_t));\n                p += sizeof(uint32_t);\n                /* GLOBALTALK READDIR CNID WIRE R7I.2 */\n                memcpy(&current_basic->fileid, p, sizeof(uint32_t));\n                p += sizeof(uint32_t);\n                memcpy(&current_basic->unixprivs, p, sizeof(struct afp_unixprivs));\n'''
    sl = replace_once(sl, old_unpack, new_unpack,
                      "readdir fileid deserialization")

    # Preserve AFP file NodeID/CNID from enumeration in the synthetic stat.
    old_stat = '''            st.st_mode = p->unixprivs.permissions;\n            st.st_size = p->size;\n            st.st_uid = p->unixprivs.uid;\n'''
    new_stat = '''            st.st_mode = p->unixprivs.permissions;\n            st.st_size = p->size;\n            /* GLOBALTALK RESUME IDENTITY R7I.2\n             * Match normal afp_sl_stat semantics: AFP NodeID/CNID -> st_ino. */\n            st.st_ino = p->fileid;\n            st.st_uid = p->unixprivs.uid;\n'''
    cmd = replace_once(cmd, old_stat, new_stat,
                       "recursive enumeration CNID propagation")

    old_check = '''        if (fresh_stat.st_size != expected_stat.st_size\n                || (expected_stat.st_ino != 0 && fresh_stat.st_ino != 0\n                    && fresh_stat.st_ino != expected_stat.st_ino)) {\n            printf("R7I: resume identity mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-cnid=%llu fresh-cnid=%llu\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (unsigned long long)expected_stat.st_ino,\n                   (unsigned long long)fresh_stat.st_ino);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n'''
    new_check = '''        /* GLOBALTALK RESUME IDENTITY R7I.2\n         * Both namespace identities must be present and equal.  Exact fork\n         * size must also match. Never fall back to pathname+size alone. */\n        if (expected_stat.st_ino == 0 || fresh_stat.st_ino == 0\n                || fresh_stat.st_ino != expected_stat.st_ino\n                || fresh_stat.st_size != expected_stat.st_size) {\n            printf("R7I.2: resume identity mismatch path=%s "\n                   "expected-size=%llu fresh-size=%llu "\n                   "expected-cnid=%llu fresh-cnid=%llu\\n",\n                   path,\n                   (unsigned long long)expected_stat.st_size,\n                   (unsigned long long)fresh_stat.st_size,\n                   (unsigned long long)expected_stat.st_ino,\n                   (unsigned long long)fresh_stat.st_ino);\n            op_ret = -ESTALE;\n            goto unrecovered;\n        }\n'''
    cmd = replace_once(cmd, old_check, new_check,
                       "strict CNID/size resume validation")

    old_retry = '''    if (recoveries > 0) {\n        printf("R7I: resuming current file path=%s offset=%llu recovery=%d/%d\\n",\n               path, offset, recoveries, max_recoveries);\n    }\n\n    if ((unsigned long long)expected_stat.st_size == total) {\n        goto complete_file;\n    }\n'''
    new_retry = '''    if ((unsigned long long)expected_stat.st_size == total) {\n        if (recoveries > 0) {\n            printf("R7I.2: data already complete after recovery; "\n                   "no fork reopen required path=%s bytes=%llu recovery=%d/%d\\n",\n                   path, total, recoveries, max_recoveries);\n        }\n        goto complete_file;\n    }\n\n    if (recoveries > 0) {\n        printf("R7I: resuming current file path=%s offset=%llu recovery=%d/%d\\n",\n               path, offset, recoveries, max_recoveries);\n    }\n'''
    cmd = replace_once(cmd, old_retry, new_retry,
                       "completed-data close recovery")

    write_text(hdr_path, hdr)
    write_text(daemon_path, daemon)
    write_text(sl_path, sl)
    write_text(cmd_path, cmd)

    print("Applied resume identity R7I.2: {}".format(root))
    print("  afpsld readdir wire now carries internal AFP fileid/CNID")
    print("  libafpsl afp_file_info_basic exposes matching fileid")
    print("  recursive enumeration fileid propagates to stat.st_ino")
    print("  resume requires nonzero matching AFP CNID + exact fork size")
    print("  zero/unavailable CNID refuses offset resume")
    print("  completed-data close recovery performs no fork reopen")
    print("  no additional AFP request added to the healthy path")


if __name__ == "__main__":
    main()
