#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7J: bounded deep recovery for old AFP servers.
#
# Layered after R7I.2.  Healthy-path AFP traffic is unchanged.  Recovery-only
# behavior is made more tolerant of classic servers that remain alive at ASP
# level but need more than one reconnect/re-prime cycle before AFP namespace
# and metadata operations become usable again.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK DEEP RECOVERY R7J"


def die(msg):
    raise SystemExit("apply_deep_recovery_r7j: " + msg)


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


def deepen_datafork_budget(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]
    old = "    const int max_recoveries = 3;\n"
    new = """    /* GLOBALTALK DEEP RECOVERY R7J\n     * Recovery-only budget.  Healthy transfers issue no extra AFP traffic. */\n    const int max_recoveries = 6;\n"""
    if func.count(old) != 1:
        die("R7I data-fork recovery budget guard missing/non-unique")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def deepen_metadata_recovery(text):
    replacement = r'''static int copy_remote_metadata_to_local(const char *remote_path,
        const char *local_path, const struct stat *st)
{
    unsigned int warnings = 0;
    int ret;
    int recovery = 0;
    const int max_recoveries = 6;

    if (transfer_metadata_mode == AFP_METADATA_NONE) {
        return 0;
    }

    /* GLOBALTALK DEEP RECOVERY R7J
     * Some classic AFP servers keep ASP/tickle service alive while an AFP
     * command path temporarily wedges.  A successful reconnect is therefore
     * not enough by itself: require the R7D parent-DID rebuild to succeed
     * before spending the next metadata operation.  Failed reconnects and
     * failed DID-primes consume the same bounded recovery budget and retry
     * after a one-second recovery-only settle interval.
     *
     * Normal metadata operations take this path exactly once and do not sleep
     * or issue any additional AFP requests. */
retry_remote_metadata:
    warnings = 0;
    ret = afp_sl_metadata_copy_remote_to_local(&vol_id, remote_path,
          local_path, transfer_metadata_mode, &warnings);
    metadata_warn(warnings);

    if (ret < 0) {
        printf("R7J: remote metadata copy failed path=%s ret=%d warnings=%u operation-attempt=%d\n",
               remote_path, ret, warnings, recovery + 1);

recover_metadata_session:
        if (recovery >= max_recoveries) {
            printf("R7J: metadata recovery budget exhausted path=%s ret=%d recoveries=%d\n",
                   remote_path, ret, recovery);
            return ret;
        }

        recovery++;
        printf("R7J: metadata recovery requested path=%s ret=%d recovery=%d/%d\n",
               remote_path, ret, recovery, max_recoveries);

        {
            int recover_ret = recover_session(1, 1);
            printf("R7J: metadata recovery result path=%s ret=%d recovery=%d/%d\n",
                   remote_path, recover_ret, recovery, max_recoveries);

            if (recover_ret != 0) {
                ret = recover_ret;
                sleep(1);
                goto recover_metadata_session;
            }
        }

        /* Give a just-reattached classic server a brief recovery-only settle
         * window before rebuilding namespace state. */
        sleep(1);

        {
            int prime_ret = r7d_prime_parent_did_chain(remote_path);
            printf("R7J: metadata recovery DID-prime path=%s ret=%d recovery=%d/%d\n",
                   remote_path, prime_ret, recovery, max_recoveries);

            if (prime_ret != 0) {
                ret = prime_ret;
                sleep(1);
                goto recover_metadata_session;
            }
        }

        printf("R7J: retrying remote metadata after recovered DID state path=%s recovery=%d/%d\n",
               remote_path, recovery, max_recoveries);
        goto retry_remote_metadata;
    }

    if (recovery > 0) {
        printf("R7J: remote metadata retry succeeded path=%s warnings=%u recoveries=%d\n",
               remote_path, warnings, recovery);
    }

    if (chmod(local_path, st->st_mode & 07777) < 0) {
        int saved_errno = errno;

        if (saved_errno != EPERM) {
            printf("R7J: local chmod failed path=%s errno=%d\n",
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
            printf("R7J: local timestamp failed path=%s errno=%d\n",
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
        die("usage: apply_deep_recovery_r7j.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Deep recovery R7J already applied: {}".format(path))
        return
    if "GLOBALTALK RESUME IDENTITY R7I.2" not in text:
        die("R7I.2 must be applied first")
    if "GLOBALTALK FINDER RECOVERY DID R7D" not in text:
        die("R7D must be applied first")

    text = deepen_datafork_budget(text)
    text = deepen_metadata_recovery(text)
    write_text(path, text)

    print("Applied deep recovery R7J: {}".format(path))
    print("  data-fork recovery budget: 6")
    print("  metadata/session recovery budget: 6")
    print("  failed reconnects consume budget and retry")
    print("  failed DID-prime never proceeds directly to metadata")
    print("  one-second settle delay exists only on recovery path")
    print("  healthy-path AFP operations and pacing unchanged")
    print("  ATP timer/retransmission budget unchanged")


if __name__ == "__main__":
    main()
