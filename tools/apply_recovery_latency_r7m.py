#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7M: data-fork recovery latency instrumentation and
# an optional poisoned-fork close bypass trial.
#
# Layered on the proven R7L / R7K tree.  Default behavior is R7L-identical:
# all recovery operations still execute, but their wall-clock latency is
# reported.  GT_AFP_R7M_SKIP_POISON_CLOSE=1 enables one isolated experiment:
# when an already-open fork is being abandoned because of a recoverable
# read/session failure or premature EOF, do not spend another AFP transaction
# trying to close that poisoned old-session fork before recover_session().
# Healthy-path FPClose behavior is never changed.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RECOVERY LATENCY R7M"


def die(msg):
    raise SystemExit("apply_recovery_latency_r7m: " + msg)


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


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


def patch_cmdline(root):
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    text = read_text(path)

    if MARKER in text:
        print("Recovery latency R7M already applied: {}".format(path))
        return
    if "GLOBALTALK DATAFORK RECOVERY LOOP R7L" not in text:
        die("R7L must be applied first")
    if "GLOBALTALK RESUME IDENTITY R7I.2" not in text:
        die("R7I.2 strict identity validation must be present")

    signature = "static int retrieve_file("
    start, end = function_span(text, signature)
    func = text[start:end]

    helper = r'''/* GLOBALTALK RECOVERY LATENCY R7M
 * Wall-clock instrumentation for the recovery path.  The optional fast-close
 * trial skips only a best-effort close of a fork that is about to be discarded
 * with the failed old session.  Successful/healthy FPClose is untouched. */
static double r7m_elapsed_ms(const struct timeval *start,
                             const struct timeval *end)
{
    return ((double)(end->tv_sec - start->tv_sec) * 1000.0)
        + ((double)(end->tv_usec - start->tv_usec) / 1000.0);
}

static int r7m_skip_poison_close(void)
{
    static int initialized = 0;
    static int cached = 0;
    const char *value;

    if (initialized) {
        return cached;
    }
    initialized = 1;
    value = getenv("GT_AFP_R7M_SKIP_POISON_CLOSE");
    if (value && strcmp(value, "1") == 0) {
        cached = 1;
    }
    return cached;
}

'''
    text = text[:start] + helper + text[start:]

    # Re-find after helper insertion.
    start, end = function_span(text, signature)
    func = text[start:end]

    func = replace_once(
        func,
        "    int recoveries = 0;\n",
        "    int recoveries = 0;\n"
        "    struct timeval r7m_t0, r7m_t1, r7m_cycle_t0;\n"
        "    int r7m_first_resume_read = 0;\n",
        "R7M local timing state")

    func = replace_once(
        func,
        "retry_file:\n    fileid = 0;\n",
        "retry_file:\n"
        "    r7m_first_resume_read = (recoveries > 0);\n"
        "    fileid = 0;\n",
        "resume-read timing arm")

    old_open = '''    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);\n    if (op_ret != 0) {\n'''
    new_open = r'''    gettimeofday(&r7m_t0, NULL);
    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
    gettimeofday(&r7m_t1, NULL);
    if (op_ret != 0) {
        printf("R7M: stage=open-failed path=%s ret=%d elapsed-ms=%.3f recovery=%d/%d\n",
               path, op_ret, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
'''
    func = replace_once(func, old_open, new_open, "open timing")

    # Successful reopen after a recovery cycle.
    old_opened = '''    file_opened = 1;\n\n    while (!eof) {\n'''
    new_opened = r'''    file_opened = 1;
    if (recoveries > 0) {
        printf("R7M: stage=resume-open path=%s elapsed-ms=%.3f recovery=%d/%d\n",
               path, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
    }

    while (!eof) {
'''
    func = replace_once(func, old_opened, new_opened, "resume open timing")

    old_read = '''        op_ret = afp_sl_read(&vol_id, fileid, 0, offset, size,\n                             &received, &eof, buf);\n        if (op_ret != 0) {\n'''
    new_read = r'''        gettimeofday(&r7m_t0, NULL);
        op_ret = afp_sl_read(&vol_id, fileid, 0, offset, size,
                             &received, &eof, buf);
        gettimeofday(&r7m_t1, NULL);
        if (op_ret != 0) {
            printf("R7M: stage=read-failed path=%s ret=%d offset=%llu "
                   "elapsed-ms=%.3f recovery=%d/%d\n",
                   path, op_ret, offset,
                   r7m_elapsed_ms(&r7m_t0, &r7m_t1),
                   recoveries, max_recoveries);
'''
    func = replace_once(func, old_read, new_read, "read failure timing")

    old_zero = '''        if (received == 0) {\n            printf("R6.1: zero-byte read path=%s offset=%llu request=%u eof=%u\\n",\n                   path, offset, size, eof);\n            break;\n        }\n'''
    new_zero = r'''        if (received == 0) {
            printf("R7M: stage=zero-read path=%s offset=%llu eof=%u "
                   "elapsed-ms=%.3f recovery=%d/%d\n",
                   path, offset, eof,
                   r7m_elapsed_ms(&r7m_t0, &r7m_t1),
                   recoveries, max_recoveries);
            printf("R6.1: zero-byte read path=%s offset=%llu request=%u eof=%u\n",
                   path, offset, size, eof);
            break;
        }
        if (r7m_first_resume_read) {
            printf("R7M: stage=first-resumed-read path=%s offset=%llu bytes=%u "
                   "elapsed-ms=%.3f recovery=%d/%d\n",
                   path, offset, received,
                   r7m_elapsed_ms(&r7m_t0, &r7m_t1),
                   recoveries, max_recoveries);
            r7m_first_resume_read = 0;
        }
'''
    func = replace_once(func, old_zero, new_zero, "zero/resume read timing")

    old_best_close = '''    if (file_opened && fileid) {\n        int close_ret = afp_sl_close(&vol_id, fileid);\n        printf("R6.1: best-effort close path=%s ret=%d\\n", path, close_ret);\n        file_opened = 0;\n        fileid = 0;\n    }\n\n    /* GLOBALTALK DATAFORK RECOVERY LOOP R7L\n'''
    new_best_close = r'''    if (file_opened && fileid) {
        int poison_failure = short_eof
            || is_recoverable_session_error(op_ret) || op_ret == -EIO;

        if (poison_failure && r7m_skip_poison_close()) {
            printf("R7M: stage=best-effort-close path=%s action=skipped "
                   "reason=poisoned-old-session ret=%d\n",
                   path, op_ret);
        } else {
            int close_ret;
            gettimeofday(&r7m_t0, NULL);
            close_ret = afp_sl_close(&vol_id, fileid);
            gettimeofday(&r7m_t1, NULL);
            printf("R6.1: best-effort close path=%s ret=%d\n", path, close_ret);
            printf("R7M: stage=best-effort-close path=%s action=issued ret=%d "
                   "elapsed-ms=%.3f\n",
                   path, close_ret, r7m_elapsed_ms(&r7m_t0, &r7m_t1));
        }
        file_opened = 0;
        fileid = 0;
    }

    /* GLOBALTALK DATAFORK RECOVERY LOOP R7L
'''
    func = replace_once(func, old_best_close, new_best_close,
                        "poisoned best-effort close trial")

    old_cycle = '''        recoveries++;\n        printf("R7I: recovery requested path=%s cause=%s ret=%d offset=%llu recovery=%d/%d\\n",\n'''
    new_cycle = r'''        gettimeofday(&r7m_cycle_t0, NULL);
        recoveries++;
        printf("R7I: recovery requested path=%s cause=%s ret=%d offset=%llu recovery=%d/%d\n",
'''
    func = replace_once(func, old_cycle, new_cycle, "recovery-cycle timer start")

    old_recover = '''        recover_ret = recover_session(1, 1);\n        printf("R7I: recovery result path=%s ret=%d recovery=%d/%d\\n",\n               path, recover_ret, recoveries, max_recoveries);\n'''
    new_recover = r'''        gettimeofday(&r7m_t0, NULL);
        recover_ret = recover_session(1, 1);
        gettimeofday(&r7m_t1, NULL);
        printf("R7I: recovery result path=%s ret=%d recovery=%d/%d\n",
               path, recover_ret, recoveries, max_recoveries);
        printf("R7M: stage=recover-session path=%s ret=%d elapsed-ms=%.3f "
               "recovery=%d/%d\n",
               path, recover_ret, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
'''
    func = replace_once(func, old_recover, new_recover, "recover-session timing")

    old_settle = '''        /* Recovery-only settle time.  Normal transfers never sleep here. */\n        sleep(1);\n\n        prime_ret = r7d_prime_parent_did_chain(path);\n'''
    new_settle = r'''        /* Recovery-only settle time.  Normal transfers never sleep here. */
        gettimeofday(&r7m_t0, NULL);
        sleep(1);
        gettimeofday(&r7m_t1, NULL);
        printf("R7M: stage=recovery-settle path=%s elapsed-ms=%.3f "
               "recovery=%d/%d\n",
               path, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);

        gettimeofday(&r7m_t0, NULL);
        prime_ret = r7d_prime_parent_did_chain(path);
        gettimeofday(&r7m_t1, NULL);
'''
    func = replace_once(func, old_settle, new_settle, "settle/DID-prime timing")

    old_prime_log = '''        printf("R7I: recovery DID-prime path=%s ret=%d recovery=%d/%d\\n",\n               path, prime_ret, recoveries, max_recoveries);\n'''
    new_prime_log = r'''        printf("R7I: recovery DID-prime path=%s ret=%d recovery=%d/%d\n",
               path, prime_ret, recoveries, max_recoveries);
        printf("R7M: stage=did-prime path=%s ret=%d elapsed-ms=%.3f "
               "recovery=%d/%d\n",
               path, prime_ret, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
'''
    func = replace_once(func, old_prime_log, new_prime_log, "DID-prime log timing")

    old_stat = '''        memset(&fresh_stat, 0, sizeof(fresh_stat));\n        op_ret = afp_sl_stat(&vol_id, path, NULL, &fresh_stat);\n        if (op_ret != 0) {\n'''
    new_stat = r'''        memset(&fresh_stat, 0, sizeof(fresh_stat));
        gettimeofday(&r7m_t0, NULL);
        op_ret = afp_sl_stat(&vol_id, path, NULL, &fresh_stat);
        gettimeofday(&r7m_t1, NULL);
        printf("R7M: stage=validation-stat path=%s ret=%d elapsed-ms=%.3f "
               "recovery=%d/%d\n",
               path, op_ret, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
        if (op_ret != 0) {
'''
    func = replace_once(func, old_stat, new_stat, "validation-stat timing")

    old_position = '''        if (ftruncate(fd, (off_t)total) != 0\n                || lseek(fd, (off_t)total, SEEK_SET) < 0) {\n'''
    new_position = r'''        gettimeofday(&r7m_t0, NULL);
        if (ftruncate(fd, (off_t)total) != 0
                || lseek(fd, (off_t)total, SEEK_SET) < 0) {
'''
    func = replace_once(func, old_position, new_position, "local position timer start")

    old_position_ok = '''        printf("R7I: resume validation passed path=%s offset=%llu "\n               "size=%llu cnid=%llu recovery=%d/%d\\n",\n               path, total,\n               (unsigned long long)expected_stat.st_size,\n               (unsigned long long)expected_stat.st_ino,\n               recoveries, max_recoveries);\n        goto retry_file;\n'''
    new_position_ok = r'''        gettimeofday(&r7m_t1, NULL);
        printf("R7M: stage=local-reposition path=%s offset=%llu elapsed-ms=%.3f "
               "recovery=%d/%d\n",
               path, total, r7m_elapsed_ms(&r7m_t0, &r7m_t1),
               recoveries, max_recoveries);
        printf("R7I: resume validation passed path=%s offset=%llu "
               "size=%llu cnid=%llu recovery=%d/%d\n",
               path, total,
               (unsigned long long)expected_stat.st_size,
               (unsigned long long)expected_stat.st_ino,
               recoveries, max_recoveries);
        gettimeofday(&r7m_t1, NULL);
        printf("R7M: stage=recovery-cycle-ready path=%s elapsed-ms=%.3f "
               "recovery=%d/%d skip-poison-close=%d\n",
               path, r7m_elapsed_ms(&r7m_cycle_t0, &r7m_t1),
               recoveries, max_recoveries, r7m_skip_poison_close());
        goto retry_file;
'''
    func = replace_once(func, old_position_ok, new_position_ok,
                        "recovery-cycle completion timing")

    text = text[:start] + func + text[end:]
    write_text(path, text)

    print("Applied recovery latency R7M: {}".format(path))
    print("  default mode: R7L behavior + recovery-stage timings")
    print("  GT_AFP_R7M_SKIP_POISON_CLOSE=0: issue/timestamp old best-effort close")
    print("  GT_AFP_R7M_SKIP_POISON_CLOSE=1: skip only poisoned recovery-path close")
    print("  healthy successful FPClose path unchanged")
    print("  open/read, close, reconnect, settle, DID-prime, stat, reposition,")
    print("  reopen and first resumed read are timestamped")
    print("  R7L six-cycle recovery and R7I.2 identity safety retained")


def main():
    if len(sys.argv) != 2:
        die("usage: apply_recovery_latency_r7m.py NETATALK_CLIENT_TREE")
    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))
    patch_cmdline(root)


if __name__ == "__main__":
    main()
