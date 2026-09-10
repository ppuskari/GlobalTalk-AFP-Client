#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R6.2 hardening.
#
# Layered after R6.1.  Diagnose metadata preservation by stage and give the
# remote AFP metadata-copy stage one bounded in-process session recovery/retry.
# Local chmod/timestamp failures are reported separately and never trigger an
# AFP reconnect.  ATP/ASP transport is deliberately untouched.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2"


def die(msg):
    raise SystemExit("apply_persistent_recursive_recovery_r6_2: " + msg)


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def function_span(text, signature):
    start = text.find(signature)
    if start < 0:
        die("function not found: {}".format(signature))
    brace = text.find("{", start)
    if brace < 0:
        die("opening brace not found: {}".format(signature))
    depth = 0
    i = brace
    state = "code"
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if c == '"':
                state = "string"
            elif c == "'":
                state = "char"
            elif c == "/" and n == "/":
                state = "linecomment"
                i += 1
            elif c == "/" and n == "*":
                state = "blockcomment"
                i += 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return start, i + 1
        elif state == "string":
            if c == "\\":
                i += 1
            elif c == '"':
                state = "code"
        elif state == "char":
            if c == "\\":
                i += 1
            elif c == "'":
                state = "code"
        elif state == "linecomment":
            if c == "\n":
                state = "code"
        elif state == "blockcomment":
            if c == "*" and n == "/":
                state = "code"
                i += 1
        i += 1
    die("unterminated function: {}".format(signature))


def replace_function(text, signature, replacement):
    start, end = function_span(text, signature)
    return text[:start] + replacement + text[end:]


def patch_metadata(text):
    replacement = r'''static int copy_remote_metadata_to_local(const char *remote_path,
        const char *local_path, const struct stat *st)
{
    unsigned int warnings = 0;
    int ret;
    int attempt = 0;

    if (transfer_metadata_mode == AFP_METADATA_NONE) {
        return 0;
    }

    /* GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.2
     * A long-lived classic AFP session can fail while copying metadata even
     * after the data fork completed correctly.  Only the remote AFP metadata
     * stage may reconnect.  Local filesystem failures are diagnosed as local
     * failures and are never used as a reason to disturb the AFP session. */
retry_remote_metadata:
    warnings = 0;
    ret = afp_sl_metadata_copy_remote_to_local(&vol_id, remote_path,
          local_path, transfer_metadata_mode, &warnings);
    metadata_warn(warnings);

    if (ret < 0) {
        int recover_ret;

        printf("R6.2: remote metadata copy failed path=%s ret=%d warnings=%u attempt=%d\n",
               remote_path, ret, warnings, attempt + 1);

        if (attempt == 0) {
            printf("R6.2: metadata recovery requested path=%s ret=%d\n",
                   remote_path, ret);
            recover_ret = recover_session(1, 1);
            printf("R6.2: metadata recovery result path=%s ret=%d\n",
                   remote_path, recover_ret);

            if (recover_ret == 0) {
                attempt = 1;
                printf("R6.2: retrying remote metadata after recovery path=%s\n",
                       remote_path);
                goto retry_remote_metadata;
            }
        }

        printf("R6.2: unrecovered remote metadata failure path=%s ret=%d\n",
               remote_path, ret);
        return ret;
    }

    if (attempt > 0) {
        printf("R6.2: remote metadata retry succeeded path=%s warnings=%u\n",
               remote_path, warnings);
    }

    if (chmod(local_path, st->st_mode & 07777) < 0) {
        int saved_errno = errno;

        if (saved_errno != EPERM) {
            printf("R6.2: local chmod failed path=%s errno=%d\n",
                   local_path, saved_errno);
            return -saved_errno;
        }
    }

    {
        struct timespec times[2] = {
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
        };

        if (utimensat(AT_FDCWD, local_path, times, 0) < 0) {
            int saved_errno = errno;
            printf("R6.2: local timestamp failed path=%s errno=%d\n",
                   local_path, saved_errno);
            return -saved_errno;
        }
    }

    return 0;
}'''
    return replace_function(text, "static int copy_remote_metadata_to_local(",
                            replacement)


def main():
    if len(sys.argv) != 2:
        die("usage: apply_persistent_recursive_recovery_r6_2.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Persistent recursive recovery R6.2 already applied: {}".format(path))
        return
    if "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.1" not in text:
        die("R6.1 must be applied first")

    text = patch_metadata(text)
    write_text(path, text)

    print("Applied persistent recursive recovery R6.2: {}".format(path))
    print("  remote AFP metadata failures get one session recovery/retry")
    print("  metadata retry remains in the same recursive copy process")
    print("  local chmod/timestamp failures are diagnosed separately")
    print("  local filesystem failures never trigger AFP reconnect")
    print("  R6.1 short-EOF recovery and fail-fast propagation retained")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
