#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7L: make data-fork recovery itself recoverable.
#
# R7I/R7J already recover an open/read/EOF failure, but a transient failure
# during the recovery sequence (reconnect, DID-prime, or validation stat)
# previously jumped directly to unrecovered.  Classic AFP servers can remain
# ASP-alive while AFP namespace/file operations need more than one recovery
# cycle.  R7L spends the existing bounded six-cycle R7J budget on the whole
# recovery state machine before giving up.
#
# Healthy path: unchanged.
# Identity safety: unchanged R7I.2 nonzero CNID + exact fork size.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK DATAFORK RECOVERY LOOP R7L"


def die(msg):
    raise SystemExit("apply_datafork_recovery_loop_r7l: " + msg)


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


def patch_retrieve(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]

    if MARKER in func:
        return text, False

    if "GLOBALTALK DEEP RECOVERY R7J" not in func:
        die("R7J data-fork recovery budget must be present first")
    if "GLOBALTALK RESUME IDENTITY R7I.2" not in func:
        die("R7I.2 strict identity validation must be present first")

    block_start = func.find("    if (recoveries < max_recoveries\n")
    if block_start < 0:
        die("R7I/R7J recovery block start not found")

    block_end = func.find("\nunrecovered:\n", block_start)
    if block_end < 0:
        die("R7I unrecovered label not found")

    replacement = r'''    /* GLOBALTALK DATAFORK RECOVERY LOOP R7L
     * Treat the recovery sequence as a bounded state machine.  A successful
     * reconnect is not sufficient evidence that an old AFP server's file
     * namespace is immediately usable.  Reconnect, DID-prime, and fresh-stat
     * failures consume the same six-cycle R7J budget and retry the recovery
     * sequence.  A real CNID/size mismatch remains immediately fatal. */
    if (short_eof || is_recoverable_session_error(op_ret)
            || op_ret == -EIO) {
        int recover_ret;
        int prime_ret;
        struct stat fresh_stat;
        const char *recover_cause =
            short_eof ? "premature-eof"
            : (op_ret == -EIO ? "remote-eio" : "session-error");

r7l_recovery_stage:
        if (recoveries >= max_recoveries) {
            printf("R7L: data-fork recovery budget exhausted path=%s ret=%d "
                   "bytes=%llu recoveries=%d/%d\n",
                   path, op_ret, total, recoveries, max_recoveries);
            goto unrecovered;
        }

        recoveries++;
        printf("R7I: recovery requested path=%s cause=%s ret=%d offset=%llu recovery=%d/%d\n",
               path, recover_cause, op_ret, total,
               recoveries, max_recoveries);

        recover_ret = recover_session(1, 1);
        printf("R7I: recovery result path=%s ret=%d recovery=%d/%d\n",
               path, recover_ret, recoveries, max_recoveries);
        if (recover_ret != 0) {
            op_ret = recover_ret;
            printf("R7L: reconnect still unusable; retrying recovery path=%s "
                   "ret=%d recovery=%d/%d\n",
                   path, op_ret, recoveries, max_recoveries);
            sleep(1);
            goto r7l_recovery_stage;
        }

        /* Recovery-only settle time.  Normal transfers never sleep here. */
        sleep(1);

        prime_ret = r7d_prime_parent_did_chain(path);
        printf("R7I: recovery DID-prime path=%s ret=%d recovery=%d/%d\n",
               path, prime_ret, recoveries, max_recoveries);
        if (prime_ret != 0) {
            op_ret = prime_ret;
            printf("R7L: DID-prime failed; retrying recovery path=%s "
                   "ret=%d recovery=%d/%d\n",
                   path, op_ret, recoveries, max_recoveries);
            sleep(1);
            goto r7l_recovery_stage;
        }

        memset(&fresh_stat, 0, sizeof(fresh_stat));
        op_ret = afp_sl_stat(&vol_id, path, NULL, &fresh_stat);
        if (op_ret != 0) {
            printf("R7I: resume validation stat failed path=%s ret=%d "
                   "recovery=%d/%d\n",
                   path, op_ret, recoveries, max_recoveries);
            if (is_recoverable_session_error(op_ret) || op_ret == -EIO) {
                printf("R7L: validation stat transient; retrying recovery path=%s "
                       "ret=%d recovery=%d/%d\n",
                       path, op_ret, recoveries, max_recoveries);
                sleep(1);
                goto r7l_recovery_stage;
            }
            goto unrecovered;
        }

        /* GLOBALTALK RESUME IDENTITY R7I.2
         * Both namespace identities must be present and equal. Exact fork
         * size must also match. Never fall back to pathname+size alone. */
        if (expected_stat.st_ino == 0 || fresh_stat.st_ino == 0
                || fresh_stat.st_ino != expected_stat.st_ino
                || fresh_stat.st_size != expected_stat.st_size) {
            printf("R7I.2: resume identity mismatch path=%s "
                   "expected-size=%llu fresh-size=%llu "
                   "expected-cnid=%llu fresh-cnid=%llu\n",
                   path,
                   (unsigned long long)expected_stat.st_size,
                   (unsigned long long)fresh_stat.st_size,
                   (unsigned long long)expected_stat.st_ino,
                   (unsigned long long)fresh_stat.st_ino);
            op_ret = -ESTALE;
            goto unrecovered;
        }

        if (fresh_stat.st_mtime != expected_stat.st_mtime) {
            printf("R7I.1: resume mtime drift ignored path=%s "
                   "expected-mtime=%lld fresh-mtime=%lld delta=%lld\n",
                   path,
                   (long long)expected_stat.st_mtime,
                   (long long)fresh_stat.st_mtime,
                   (long long)fresh_stat.st_mtime
                       - (long long)expected_stat.st_mtime);
        }

        if (ftruncate(fd, (off_t)total) != 0
                || lseek(fd, (off_t)total, SEEK_SET) < 0) {
            printf("R7I: could not position local partial file path=%s offset=%llu\n",
                   path, total);
            ret = -1;
            goto out;
        }

        printf("R7I: resume validation passed path=%s offset=%llu "
               "size=%llu cnid=%llu recovery=%d/%d\n",
               path, total,
               (unsigned long long)expected_stat.st_size,
               (unsigned long long)expected_stat.st_ino,
               recoveries, max_recoveries);
        goto retry_file;
    }
'''

    func = func[:block_start] + replacement + func[block_end:]
    return text[:start] + func + text[end:], True


def main():
    if len(sys.argv) != 2:
        die("usage: apply_datafork_recovery_loop_r7l.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("Data-fork recovery loop R7L already applied: {}".format(path))
        return
    if "GLOBALTALK DEEP RECOVERY R7J" not in text:
        die("R7J must be applied first")
    if "GLOBALTALK FINDER TOLERANCE R7K" not in text:
        die("R7K must be applied first")

    text, changed = patch_retrieve(text)
    if not changed:
        die("R7L patch unexpectedly made no change")

    write_text(path, text)
    print("Applied data-fork recovery loop R7L: {}".format(path))
    print("  healthy data path unchanged")
    print("  existing R7J recovery budget remains 6 cycles")
    print("  reconnect failure retries within that budget")
    print("  DID-prime failure retries within that budget")
    print("  transient resume-validation stat failure retries within that budget")
    print("  strict R7I.2 CNID + exact-size identity check remains mandatory")
    print("  real identity mismatch still aborts immediately")
    print("  one-second settle exists only inside recovery")


if __name__ == "__main__":
    main()
