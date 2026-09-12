#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7H: known-size resource-fork open.
#
# R7F already knows the resource-fork length before the R4 stateful stream is
# opened.  R7G taught AFP2 ll_open() to trust an explicitly known fork size.
# Carry that same information through the R4 resource-open path so AFP2 can go
# directly to FPOpenFork instead of repeating FPGetFileDirParms.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK KNOWN RESOURCE OPEN R7H"
R7G_MARKER = "GLOBALTALK KNOWN DATA OPEN R7G"


def die(msg):
    raise SystemExit("apply_known_resource_open_r7h: " + msg)


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


def patch_resource_h(text):
    old = '''int appledouble_open_meta(struct afp_volume * volume, const char * path,
                          unsigned int resource, int flags,
                          struct afp_file_info *fp);
'''
    new = old + '''/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
int appledouble_open_meta_known(struct afp_volume *volume, const char *path,
                                unsigned int resource, int flags,
                                unsigned long long known_size,
                                struct afp_file_info *fp);
'''
    return replace_once(text, old, new, "appledouble known-open declaration")


def patch_resource_c(text):
    if "int appledouble_open_meta_known(" in text:
        return text
    start, end = function_span(text, "int appledouble_open_meta(")
    helper = r'''

/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
int appledouble_open_meta_known(struct afp_volume *volume, const char *path,
                                unsigned int resource, int flags,
                                unsigned long long known_size,
                                struct afp_file_info *fp)
{
    if (!volume || !path || !fp) {
        return -EINVAL;
    }

    memset(fp, 0, sizeof(*fp));
    fp->resource = resource;

    switch (resource) {
    case AFP_META_RESOURCE:
        if (get_dirid(volume, path, fp->basename, &fp->did) < 0) {
            return -ENOENT;
        }
        fp->resourcesize = known_size;
        fp->r7g_known_size_valid = 1;
        return ll_open(volume, path, flags, fp);

    case AFP_META_FINDERINFO:
        if (get_dirid(volume, path, fp->basename, &fp->did) < 0) {
            return -ENOENT;
        }
        return 0;

    default:
        return -EINVAL;
    }
}
'''
    return text[:end] + helper + text[end:]


def patch_midlevel_h(text):
    old = '''int ml_open_resourcefork(struct afp_volume *volume, const char *path,
                         int flags, struct afp_file_info **newfp);
'''
    new = old + '''/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
int ml_open_resourcefork_known(struct afp_volume *volume, const char *path,
                               int flags, unsigned long long known_size,
                               struct afp_file_info **newfp);
'''
    return replace_once(text, old, new, "ml resource known-open declaration")


def patch_midlevel_c(text):
    if "int ml_open_resourcefork_known(" in text:
        return text

    start, end = function_span(text, "static int open_appledouble_meta(")
    helper = r'''

/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
static int open_appledouble_meta_known(struct afp_volume *volume,
                                       const char *path,
                                       unsigned int resource, int flags,
                                       unsigned long long known_size,
                                       struct afp_file_info *fp)
{
    char converted_path[AFP_MAX_PATH];

    if (!volume || !path || !fp) {
        return -EINVAL;
    }

    if (convert_path_to_afp(volume->server->path_encoding,
                            converted_path, (char *)path, AFP_MAX_PATH)) {
        return -EINVAL;
    }

    if (invalid_filename(volume->server, converted_path)) {
        return -ENAMETOOLONG;
    }

    return appledouble_open_meta_known(volume, converted_path, resource,
                                       flags, known_size, fp);
}
'''
    text = text[:end] + helper + text[end:]

    start, end = function_span(text, "int ml_open_resourcefork(")
    helper = r'''

/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
int ml_open_resourcefork_known(struct afp_volume *volume, const char *path,
                               int flags, unsigned long long known_size,
                               struct afp_file_info **newfp)
{
    struct afp_file_info *fp;
    int ret;

    if (!volume || !path || !newfp) {
        return -EINVAL;
    }

    fp = calloc(1, sizeof(*fp));
    if (!fp) {
        return -ENOMEM;
    }

    ret = open_appledouble_meta_known(volume, path, AFP_META_RESOURCE,
                                      flags, known_size, fp);
    if (ret < 0) {
        free(fp);
        return ret;
    }

    *newfp = fp;
    return 0;
}
'''
    return text[:end] + helper + text[end:]


def patch_afpsl_h(text):
    old = '''int afp_sl_open_resourcefork(volumeid_t *volid, const char *path,
                             struct afp_url *url, unsigned int *fileid,
                             unsigned int mode);
'''
    new = old + '''/* GLOBALTALK KNOWN RESOURCE OPEN R7H */
int afp_sl_open_resourcefork_known(volumeid_t *volid, const char *path,
                                   struct afp_url *url,
                                   unsigned int *fileid,
                                   unsigned int mode,
                                   unsigned long long known_size);
'''
    return replace_once(text, old, new, "resource known-open stateless declaration")


def patch_stateless(text):
    if "int afp_sl_open_resourcefork_known(" in text:
        return text
    start, end = function_span(text, "int afp_sl_open_resourcefork(")
    original = text[start:end]
    if "request.resource = 1;" not in original:
        die("R4 resource selector missing")

    clone = original.replace("int afp_sl_open_resourcefork(",
                             "int afp_sl_open_resourcefork_known(", 1)
    clone = clone.replace("unsigned int mode)\n{",
                          "unsigned int mode,\n"
                          "                                   unsigned long long known_size)\n{", 1)
    if clone == original:
        die("could not form known-resource stateless signature")

    clone = clone.replace(
        "    request.resource = 1;\n",
        "    request.resource = 1;\n"
        "    request.known_size_valid = 1;\n"
        "    request.known_size = known_size;\n", 1)
    clone = "\n\n/* {} */\n".format(MARKER) + clone
    return text[:end] + clone + text[end:]


def patch_commands(text):
    start, end = function_span(text, "static unsigned char process_open(")
    func = text[start:end]
    old = '''    if (request->resource) {
        ret = ml_open_resourcefork(v, request->path, request->mode, &fp);
    } else if (request->known_size_valid) {
'''
    new = '''    if (request->resource && request->known_size_valid) {
        /* GLOBALTALK KNOWN RESOURCE OPEN R7H */
        ret = ml_open_resourcefork_known(v, request->path, request->mode,
                                         request->known_size, &fp);
    } else if (request->resource) {
        ret = ml_open_resourcefork(v, request->path, request->mode, &fp);
    } else if (request->known_size_valid) {
'''
    if old not in func:
        die("R7G process_open selector not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_metadata(text):
    start, end = function_span(text, "static int stream_remote_resourcefork_to_local(")
    func = text[start:end]
    old = '''    ret = afp_sl_open_resourcefork(source_volume, source_path, NULL,
                                   &fileid, O_RDONLY);
'''
    new = '''    /* GLOBALTALK KNOWN RESOURCE OPEN R7H
     * 'total' came either from R7F FPEnumerate metadata or from a fresh
     * post-recovery size query, so it is safe for this session/open. */
    ret = afp_sl_open_resourcefork_known(source_volume, source_path, NULL,
                                         &fileid, O_RDONLY, total);
'''
    count = func.count(old)
    if count != 1:
        die("R4 resource stream open: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_known_resource_open_r7h.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    paths = {
        "resource_h": os.path.join(root, "lib", "resource.h"),
        "resource_c": os.path.join(root, "lib", "resource.c"),
        "midlevel_h": os.path.join(root, "lib", "midlevel.h"),
        "midlevel_c": os.path.join(root, "lib", "midlevel.c"),
        "afpsl": os.path.join(root, "include", "afpsl.h"),
        "stateless": os.path.join(root, "daemon", "stateless.c"),
        "commands": os.path.join(root, "daemon", "commands.c"),
        "metadata": os.path.join(root, "daemon", "metadata.c"),
        "afp": os.path.join(root, "include", "afp.h"),
    }

    for path in paths.values():
        if not os.path.isfile(path):
            die("missing {}".format(path))

    if R7G_MARKER not in read_text(paths["afp"]):
        die("R7G must be applied first")
    if MARKER in read_text(paths["afpsl"]):
        print("Known resource open R7H already applied: {}".format(root))
        return

    write_text(paths["resource_h"], patch_resource_h(read_text(paths["resource_h"])))
    write_text(paths["resource_c"], patch_resource_c(read_text(paths["resource_c"])))
    write_text(paths["midlevel_h"], patch_midlevel_h(read_text(paths["midlevel_h"])))
    write_text(paths["midlevel_c"], patch_midlevel_c(read_text(paths["midlevel_c"])))
    write_text(paths["afpsl"], patch_afpsl_h(read_text(paths["afpsl"])))
    write_text(paths["stateless"], patch_stateless(read_text(paths["stateless"])))
    write_text(paths["commands"], patch_commands(read_text(paths["commands"])))
    write_text(paths["metadata"], patch_metadata(read_text(paths["metadata"])))

    print("Applied known resource-fork open R7H")
    print("  R4 stateful resource stream keeps one open fork")
    print("  known resource length skips AFP2 pre-open parameter query")
    print("  size is authoritative from R7F or fresh post-recovery query")
    print("  resource reads and close semantics unchanged")
    print("  R7G known data open retained")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
