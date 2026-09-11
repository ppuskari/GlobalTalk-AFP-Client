#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7C: Finder-style directory-ID reuse.
#
# R7B proved that avoiding redundant per-file path stat calls materially
# improves both reliability and throughput on classic AFP servers.  A remaining
# failure showed an object returned by FPEnumerate immediately failing a later
# full-path open with ENOENT.  Netatalk Client 0.9.5 resolves that open by
# re-walking the parent pathname through get_dirid(), despite FPEnumerate
# already returning each child's ParentDirID.
#
# R7C seeds the existing DID cache from the FPEnumerate result for the directory
# being walked, then keeps actively used cache entries alive with a sliding
# timeout.  Subsequent opens therefore resolve the parent directory by DID and
# issue only the direct child-name AFP operation, which is much closer to
# classic Finder behavior.
#
# ATP/ASP transport, AFP read sizing, resource forks, metadata handling, and
# R6 recovery behavior are deliberately untouched.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK FINDER DID CACHE R7C"
R7B_MARKER = "GLOBALTALK FINDER ENUM METADATA R7B"


def die(msg):
    raise SystemExit("apply_finder_did_cache_r7c: " + msg)


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


def patch_did(did_text):
    old_hit = '''        if (strcmp(p->dirname, path) == 0) {\n            found_did = p->did;\n            volume->did_cache_stats.hits++;\n            goto out;\n        }\n'''
    new_hit = '''        if (strcmp(p->dirname, path) == 0) {\n            /* GLOBALTALK FINDER DID CACHE R7C */\n            found_did = p->did;\n            p->time = time;\n            volume->did_cache_stats.hits++;\n            goto out;\n        }\n'''
    did_text = replace_once(did_text, old_hit, new_hit,
                            "DID sliding cache hit")

    start, end = function_span(did_text, "static int add_did_cache_entry(")
    helper = r'''

/* GLOBALTALK FINDER DID CACHE R7C
 * Seed the current directory DID directly from an FPEnumerate result.
 * 'path' is already in AFP path encoding here, matching get_dirid() keys. */
int seed_did_cache_from_enumerate(struct afp_volume *volume,
                                  const char *path,
                                  struct afp_file_info *entries)
{
    char cache_path[AFP_MAX_PATH];
    size_t path_len;

    if (!volume || !path || !entries || entries->parentdid == 0) {
        return -1;
    }

    if (strcmp(path, "/") == 0) {
        return 0;
    }

    path_len = strlen(path);
    if (path_len >= sizeof(cache_path)) {
        return -1;
    }

    memset(cache_path, 0, sizeof(cache_path));
    memcpy(cache_path, path, path_len + 1U);
    return add_did_cache_entry(volume, entries->parentdid, cache_path);
}
'''
    did_text = did_text[:end] + helper + did_text[end:]
    return did_text


def patch_did_header(h_text):
    old = '''int get_dirid(struct afp_volume * volume, const char * path,\n              char *basename, unsigned int *dirid);\n\n#endif\n'''
    new = '''int get_dirid(struct afp_volume * volume, const char * path,\n              char *basename, unsigned int *dirid);\nint seed_did_cache_from_enumerate(struct afp_volume *volume,\n                                  const char *path,\n                                  struct afp_file_info *entries);\n\n#endif\n'''
    return replace_once(h_text, old, new, "did.h R7C declaration")


def patch_lowlevel(text):
    old_vars = '''    int rc = 0, ret = 0, exit = 0;\n    unsigned int filebitmap, dirbitmap;\n'''
    new_vars = '''    int rc = 0, ret = 0, exit = 0;\n    int r7c_did_seeded = 0;\n    unsigned int filebitmap, dirbitmap;\n'''
    text = replace_once(text, old_vars, new_vars,
                        "ll_readdir R7C seed state")

    old_case = '''        case 0:\n        case kFPObjectNotFound:\n            if (filebase == NULL) {\n                filebase = base;\n            } else {\n                last->next = base;\n            }\n'''
    new_case = '''        case 0:\n        case kFPObjectNotFound:\n            /* GLOBALTALK FINDER DID CACHE R7C\n             * Reuse the ParentDirID carried by FPEnumerate instead of making\n             * later child opens rediscover this directory from its full path. */\n            if (!r7c_did_seeded && base != NULL\n                    && seed_did_cache_from_enumerate(volume, path, base) == 0) {\n                r7c_did_seeded = 1;\n            }\n\n            if (filebase == NULL) {\n                filebase = base;\n            } else {\n                last->next = base;\n            }\n'''
    text = replace_once(text, old_case, new_case,
                        "ll_readdir R7C enumerate seed")
    return text


def main():
    if len(sys.argv) != 2:
        die("usage: apply_finder_did_cache_r7c.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    cmdline = os.path.join(root, "cmdline", "cmdline_afp.c")
    did_c = os.path.join(root, "lib", "did.c")
    did_h = os.path.join(root, "lib", "did.h")
    lowlevel = os.path.join(root, "lib", "lowlevel.c")

    for path in (cmdline, did_c, did_h, lowlevel):
        if not os.path.isfile(path):
            die("missing {}".format(path))

    cmd_text = read_text(cmdline)
    if R7B_MARKER not in cmd_text:
        die("R7B must be applied first")

    did_text = read_text(did_c)
    if MARKER in did_text:
        print("Finder DID cache R7C already applied: {}".format(did_c))
        return

    did_text = patch_did(did_text)
    header_text = patch_did_header(read_text(did_h))
    low_text = patch_lowlevel(read_text(lowlevel))

    write_text(did_c, did_text)
    write_text(did_h, header_text)
    write_text(lowlevel, low_text)

    print("Applied Finder DID cache R7C")
    print("  FPEnumerate ParentDirID seeds the current-directory DID cache")
    print("  actively used DID cache entries get a sliding timeout refresh")
    print("  child open resolves parent by DID instead of re-walking full path")
    print("  AFP child open/read/close commands themselves are unchanged")
    print("  ATP/ASP transport, 4624-byte ceiling, and R7A retry unchanged")
    print("  R7B enumeration-metadata reuse retained")


if __name__ == "__main__":
    main()
