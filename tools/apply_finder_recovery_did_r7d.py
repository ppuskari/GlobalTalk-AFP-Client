#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7D: preserve Finder-style DID traversal across
# session recovery.
#
# R7C seeds the daemon's DID cache from FPEnumerate and uses a sliding timeout.
# A reconnect/reattach necessarily creates or reinitializes volume state, so
# that cache can be empty immediately after recover_session().  The next
# metadata/open/list operation then falls back to a full pathname walk, which
# classic AFP servers can intermittently reject even though the object was
# just enumerated.
#
# R7D rebuilds only the parent DID chain after a successful recovery.  It walks
# directory components from the root one level at a time using a one-entry
# FPEnumerate.  R7C consumes each returned ParentDirID and seeds the cache, so
# the target operation again uses parent DID + child basename like Finder.
#
# Normal no-error traffic is unchanged.  ATP/ASP transport, read sizes,
# resource forks, metadata semantics, and retry budgets are unchanged.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK FINDER RECOVERY DID R7D"
R7C_MARKER = "GLOBALTALK FINDER DID CACHE R7C"


def die(msg):
    raise SystemExit("apply_finder_recovery_did_r7d: " + msg)


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


def insert_helper(text):
    start, end = function_span(text, "static int recover_session(")
    helper = r'''

/* GLOBALTALK FINDER RECOVERY DID R7D
 * Rebuild the daemon-side parent DID cache after reconnect/reattach.  Walk
 * from the AFP root one directory component at a time.  R7C's ll_readdir()
 * hook consumes each FPEnumerate ParentDirID and seeds that exact pathname.
 *
 * This is recovery-only traffic.  The normal persistent-session hot path is
 * unchanged. */
static int r7d_prime_parent_did_chain(const char *remote_path)
{
    char parent[AFP_MAX_PATH];
    char partial[AFP_MAX_PATH];
    char *last_slash;
    const char *scan;

    if (!remote_path || remote_path[0] != '/') {
        return -EINVAL;
    }

    if (strlcpy(parent, remote_path, sizeof(parent)) >= sizeof(parent)) {
        return -ENAMETOOLONG;
    }

    last_slash = strrchr(parent, '/');
    if (!last_slash || last_slash == parent) {
        return 0;
    }
    *last_slash = '\0';

    partial[0] = '\0';
    scan = parent;

    while (*scan != '\0') {
        const char *next;
        size_t component_len;
        size_t used;
        struct afp_file_info_basic *probe = NULL;
        unsigned int probe_count = 0;
        int eod = 0;
        int ret;

        if (*scan == '/') {
            scan++;
        }
        if (*scan == '\0') {
            break;
        }

        next = strchr(scan, '/');
        component_len = next ? (size_t)(next - scan) : strlen(scan);
        used = strlen(partial);

        if (component_len == 0
                || used + 1U + component_len + 1U > sizeof(partial)) {
            return -ENAMETOOLONG;
        }

        partial[used++] = '/';
        memcpy(partial + used, scan, component_len);
        used += component_len;
        partial[used] = '\0';

        ret = afp_sl_readdir(&vol_id, partial, NULL, 0, 1,
                             &probe_count, &probe, &eod);
        free(probe);

        if (ret != 0) {
            return ret;
        }

        /* Every directory in this chain contains either the next directory
         * component or, for the final parent, the target object itself. */
        if (probe_count == 0) {
            return -ENOENT;
        }

        if (!next) {
            break;
        }
        scan = next;
    }

    return 0;
}
'''
    return text[:end] + helper + text[end:]


def patch_metadata_recovery(text):
    old = '''            if (recover_ret == 0) {\n                attempt = 1;\n                printf("R6.2: retrying remote metadata after recovery path=%s\\n",\n                       remote_path);\n                goto retry_remote_metadata;\n            }\n'''
    new = '''            if (recover_ret == 0) {\n                int prime_ret = r7d_prime_parent_did_chain(remote_path);\n                printf("R7D: metadata recovery DID-prime path=%s ret=%d\\n",\n                       remote_path, prime_ret);\n                attempt = 1;\n                printf("R6.2: retrying remote metadata after recovery path=%s\\n",\n                       remote_path);\n                goto retry_remote_metadata;\n            }\n'''
    return replace_once(text, old, new, "metadata recovery DID prime")


def patch_file_recovery(text):
    old = '''        if (recover_ret == 0) {\n            attempt = 1;\n            goto retry_file;\n        }\n'''
    new = '''        if (recover_ret == 0) {\n            int prime_ret = r7d_prime_parent_did_chain(path);\n            printf("R7D: file recovery DID-prime path=%s ret=%d\\n",\n                   path, prime_ret);\n            attempt = 1;\n            goto retry_file;\n        }\n'''
    # R6.4's retrieve_file contains exactly one copy of this compact guard.
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]
    func = replace_once(func, old, new, "file recovery DID prime")
    return text[:start] + func + text[end:]


def patch_directory_stat_recovery(text):
    old = '''                if (recover_ret == 0) {\n                    dir_stat_attempt = 1;\n                    goto retry_directory_stat;\n                }\n'''
    new = '''                if (recover_ret == 0) {\n                    int prime_ret = r7d_prime_parent_did_chain(server_path);\n                    printf("R7D: directory-stat recovery DID-prime path=%s ret=%d\\n",\n                           display_text(server_path, display_remote,\n                                        sizeof(display_remote)),\n                           prime_ret);\n                    dir_stat_attempt = 1;\n                    goto retry_directory_stat;\n                }\n'''
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]
    func = replace_once(func, old, new, "directory stat recovery DID prime")
    return text[:start] + func + text[end:]


def patch_readdir_recovery(text):
    old = '''            if (recover_session(1, 1) == 0) {\n                retried = 1;\n                printf("R6: recovered AFP session while listing %s; retrying page at entry %lu\\n",\n                       path, (unsigned long)total);\n                goto retry_page;\n            }\n'''
    new = '''            if (recover_session(1, 1) == 0) {\n                int prime_ret = r7d_prime_parent_did_chain(path);\n                printf("R7D: directory-list recovery DID-prime path=%s ret=%d\\n",\n                       path, prime_ret);\n                retried = 1;\n                printf("R6: recovered AFP session while listing %s; retrying page at entry %lu\\n",\n                       path, (unsigned long)total);\n                goto retry_page;\n            }\n'''
    start, end = function_span(text, "static int remote_readdir_all(")
    func = text[start:end]
    func = replace_once(func, old, new, "directory list recovery DID prime")
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_finder_recovery_did_r7d.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    cmdline = os.path.join(root, "cmdline", "cmdline_afp.c")
    did_c = os.path.join(root, "lib", "did.c")

    if not os.path.isfile(cmdline) or not os.path.isfile(did_c):
        die("patched Netatalk Client tree not found: {}".format(root))

    text = read_text(cmdline)
    did_text = read_text(did_c)

    if MARKER in text:
        print("Finder recovery DID R7D already applied: {}".format(cmdline))
        return

    if R7C_MARKER not in did_text:
        die("R7C must be applied first")
    if "GLOBALTALK PERSISTENT RECURSIVE RECOVERY R6.4" not in text:
        die("R6.4 must be applied first")

    text = insert_helper(text)
    text = patch_metadata_recovery(text)
    text = patch_file_recovery(text)
    text = patch_directory_stat_recovery(text)
    text = patch_readdir_recovery(text)
    write_text(cmdline, text)

    print("Applied Finder recovery DID R7D: {}".format(cmdline))
    print("  successful reconnects rebuild the parent DID chain one level at a time")
    print("  metadata retry reuses R7C DID semantics after reattach")
    print("  file retry reuses R7C DID semantics after reattach")
    print("  directory stat/list retry reuses R7C DID semantics after reattach")
    print("  DID priming is recovery-only; normal traffic is unchanged")
    print("  ATP/ASP transport, 4624-byte ceiling, reads, and retry budget unchanged")


if __name__ == "__main__":
    main()
