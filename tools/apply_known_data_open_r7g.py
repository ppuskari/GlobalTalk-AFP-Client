#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7G: known-size data-fork open.
#
# For AFP 2.x, Netatalk's ll_open() normally performs FPGetFileDirParms before
# FPOpenFork to obtain the fork length.  R7F already carries the authoritative
# data-fork length from FPEnumerate (or the direct caller's stat), so the
# healthy path can skip that extra wire transaction.  Recovery retries use the
# conservative normal open path.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK KNOWN DATA OPEN R7G"
R7F_MARKER = "GLOBALTALK ENUMERATED METADATA R7F"


def die(msg):
    raise SystemExit("apply_known_data_open_r7g: " + msg)


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


def patch_afp_h(text):
    old = '''    unsigned long long resourcesize;
    unsigned int resource;
    unsigned short forkid;
'''
    new = '''    unsigned long long resourcesize;
    unsigned int resource;
    unsigned short forkid;
    /* GLOBALTALK KNOWN DATA OPEN R7G */
    unsigned char r7g_known_size_valid;
'''
    return replace_once(text, old, new, "afp_file_info known-size flag")


def patch_lowlevel(text):
    start, end = function_span(text, "int ll_open(")
    func = text[start:end]
    old = '''    if (volume->server->using_version->av_number < 30) {
        switch (ll_get_directory_entry(volume, fp->basename, fp->did,
                                       kFPParentDirIDBit | kFPNodeIDBit |
                                       (fp->resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),
                                       0, fp)) {
        case kFPAccessDenied:
            ret = EACCES;
            goto error;

        case kFPObjectNotFound:
            ret = ENOENT;
            goto error;

        case kFPNoErr:
            break;

        case kFPBitmapErr:
        case kFPMiscErr:
        case kFPParamErr:
        default:
            ret = EIO;
            goto error;
        }

        if ((fp->resource ? (fp->resourcesize >= (AFP_MAX_AFP2_FILESIZE - 1)) :
                (fp->size >= AFP_MAX_AFP2_FILESIZE - 1))) {
            /* According to p.30, if the server doesn't support >4GB files
               and the file being opened is >4GB, then resourcesize or size
               will return 4GB.  How can it return 4GB in 32 bits?  I
               suspect it actually returns 4GB-1.
            */
            ret = EOVERFLOW;
            goto error;
        }
    }
'''
    new = '''    if (volume->server->using_version->av_number < 30) {
        /* GLOBALTALK KNOWN DATA OPEN R7G
         * A healthy recursive/direct download already has the exact fork
         * length.  Avoid re-querying the same object immediately before
         * FPOpenFork.  Normal opens and recovery retries retain the original
         * FPGetFileDirParms behavior. */
        if (!fp->r7g_known_size_valid) {
            switch (ll_get_directory_entry(volume, fp->basename, fp->did,
                                           kFPParentDirIDBit | kFPNodeIDBit |
                                           (fp->resource ? kFPRsrcForkLenBit : kFPDataForkLenBit),
                                           0, fp)) {
            case kFPAccessDenied:
                ret = EACCES;
                goto error;

            case kFPObjectNotFound:
                ret = ENOENT;
                goto error;

            case kFPNoErr:
                break;

            case kFPBitmapErr:
            case kFPMiscErr:
            case kFPParamErr:
            default:
                ret = EIO;
                goto error;
            }
        }

        if ((fp->resource ? (fp->resourcesize >= (AFP_MAX_AFP2_FILESIZE - 1)) :
                (fp->size >= AFP_MAX_AFP2_FILESIZE - 1))) {
            /* According to p.30, if the server doesn't support >4GB files
               and the file being opened is >4GB, then resourcesize or size
               will return 4GB.  How can it return 4GB in 32 bits?  I
               suspect it actually returns 4GB-1.
            */
            ret = EOVERFLOW;
            goto error;
        }
    }
'''
    if old not in func:
        die("AFP2 ll_open pre-open parameter block not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_midlevel_h(text):
    old = '''int ml_open(struct afp_volume * volume, const char *path, int flags,
            struct afp_file_info **newfp);
'''
    new = old + '''/* GLOBALTALK KNOWN DATA OPEN R7G */
int ml_open_known_data(struct afp_volume *volume, const char *path, int flags,
                       unsigned long long known_size,
                       struct afp_file_info **newfp);
'''
    return replace_once(text, old, new, "ml_open_known_data declaration")


def patch_midlevel(text):
    if "int ml_open_known_data(" in text:
        return text
    start, end = function_span(text, "int ml_open(")
    helper = r'''

/* GLOBALTALK KNOWN DATA OPEN R7G
 * Same lifetime/handle semantics as ml_open(), but seed the already-known data
 * fork size so ll_open() can go directly to FPOpenFork on AFP 2.x. */
int ml_open_known_data(struct afp_volume *volume, const char *path, int flags,
                       unsigned long long known_size,
                       struct afp_file_info **newfp)
{
    struct afp_file_info *fp;
    int ret;
    unsigned int dirid;
    char *converted_path;

    ret = convert_path_to_afp_alloc(volume->path_encoding, path,
                                    &converted_path);
    if (ret) {
        return ret;
    }

    if (invalid_filename(volume, converted_path)) {
        free(converted_path);
        return -ENAMETOOLONG;
    }

    if (volume_is_readonly(volume) &&
            (flags & (O_WRONLY | O_RDWR | O_TRUNC | O_APPEND | O_CREAT))) {
        free(converted_path);
        return -EACCES;
    }

    fp = malloc(sizeof(*fp));
    if (!fp) {
        free(converted_path);
        return -ENOMEM;
    }

    *newfp = fp;
    memset(fp, 0, sizeof(*fp));
    ret = appledouble_open(volume, path, flags, fp);
    if (ret < 0) {
        free(fp);
        free(converted_path);
        return ret;
    }

    if (ret == 1) {
        goto out;
    }

    if (get_dirid(volume, converted_path, fp->basename, &dirid) < 0) {
        ret = -ENOENT;
        goto error;
    }

    fp->did = dirid;
    fp->size = known_size;
    fp->r7g_known_size_valid = 1;
    ret = ll_open(volume, converted_path, flags, fp);
    if (ret < 0) {
        goto error;
    }

out:
    free(converted_path);
    return 0;
error:
    free(fp);
    free(converted_path);
    return ret;
}
'''
    return text[:end] + helper + text[end:]


def patch_server_h(text):
    old = '''    int mode;
    /* GLOBALTALK RFORK R4 STATEFUL STREAM */
    unsigned int resource;
};
'''
    new = '''    int mode;
    /* GLOBALTALK RFORK R4 STATEFUL STREAM */
    unsigned int resource;
    /* GLOBALTALK KNOWN DATA OPEN R7G */
    unsigned int known_size_valid;
    unsigned long long known_size;
};
'''
    return replace_once(text, old, new, "open request known-size fields")


def patch_afpsl_h(text):
    old = '''int afp_sl_open(volumeid_t * volid, const char * path,
                struct afp_url * url, unsigned int *fileid,
                unsigned int mode);
'''
    if old not in text:
        old = '''int afp_sl_open(volumeid_t *volid, const char *path, struct afp_url *url,
                unsigned int *fileid, unsigned int mode);
'''
    new = old + '''/* GLOBALTALK KNOWN DATA OPEN R7G */
int afp_sl_open_known_data(volumeid_t *volid, const char *path,
                           struct afp_url *url, unsigned int *fileid,
                           unsigned int mode,
                           unsigned long long known_size);
'''
    return replace_once(text, old, new, "afp_sl_open_known_data declaration")


def patch_stateless(text):
    if "int afp_sl_open_known_data(" in text:
        return text

    start, end = function_span(text, "int afp_sl_open(")
    original = text[start:end]
    if "request.resource = 0;" not in original:
        die("R4 data-open resource selector missing")

    clone = original.replace("int afp_sl_open(",
                             "int afp_sl_open_known_data(", 1)
    clone = clone.replace("unsigned int mode)\n{",
                          "unsigned int mode,\n"
                          "                           unsigned long long known_size)\n{", 1)
    if clone == original:
        die("could not form known-data stateless open signature")

    clone = clone.replace(
        "    request.resource = 0;\n",
        "    request.resource = 0;\n"
        "    request.known_size_valid = 1;\n"
        "    request.known_size = known_size;\n", 1)

    # memset() already keeps normal and R4 resource opens conservative.
    clone = "\n\n/* {} */\n".format(MARKER) + clone
    return text[:end] + clone + text[end:]


def patch_commands(text):
    start, end = function_span(text, "static unsigned char process_open(")
    func = text[start:end]
    old = '''    if (request->resource) {
        ret = ml_open_resourcefork(v, request->path, request->mode, &fp);
    } else {
        ret = ml_open(v, request->path, request->mode, &fp);
    }
'''
    new = '''    if (request->resource) {
        ret = ml_open_resourcefork(v, request->path, request->mode, &fp);
    } else if (request->known_size_valid) {
        /* GLOBALTALK KNOWN DATA OPEN R7G */
        ret = ml_open_known_data(v, request->path, request->mode,
                                 request->known_size, &fp);
    } else {
        ret = ml_open(v, request->path, request->mode, &fp);
    }
'''
    if old not in func:
        die("R4 process_open selector not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_cmdline(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]
    old = '''    op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
'''
    new = '''    /* GLOBALTALK KNOWN DATA OPEN R7G
     * The healthy path already owns exact size metadata.  After recovery use
     * the conservative open so no pre-recovery snapshot crosses sessions. */
    if (attempt == 0 && stat) {
        op_ret = afp_sl_open_known_data(&vol_id, path, NULL, &fileid,
                                        O_RDONLY,
                                        (unsigned long long)stat->st_size);
    } else {
        op_ret = afp_sl_open(&vol_id, path, NULL, &fileid, O_RDONLY);
    }
'''
    count = func.count(old)
    if count != 1:
        die("retrieve data open: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_known_data_open_r7g.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    paths = {
        "afp": os.path.join(root, "include", "afp.h"),
        "afpsl": os.path.join(root, "include", "afpsl.h"),
        "server": os.path.join(root, "include", "afp_server.h"),
        "lowlevel": os.path.join(root, "lib", "lowlevel.c"),
        "midlevel_h": os.path.join(root, "lib", "midlevel.h"),
        "midlevel": os.path.join(root, "lib", "midlevel.c"),
        "stateless": os.path.join(root, "daemon", "stateless.c"),
        "commands": os.path.join(root, "daemon", "commands.c"),
        "cmdline": os.path.join(root, "cmdline", "cmdline_afp.c"),
    }

    for path in paths.values():
        if not os.path.isfile(path):
            die("missing {}".format(path))

    cmd_text = read_text(paths["cmdline"])
    if R7F_MARKER not in read_text(paths["afpsl"]):
        die("R7F must be applied first")
    if MARKER in cmd_text:
        print("Known data open R7G already applied: {}".format(root))
        return

    write_text(paths["afp"], patch_afp_h(read_text(paths["afp"])))
    write_text(paths["lowlevel"], patch_lowlevel(read_text(paths["lowlevel"])))
    write_text(paths["midlevel_h"], patch_midlevel_h(read_text(paths["midlevel_h"])))
    write_text(paths["midlevel"], patch_midlevel(read_text(paths["midlevel"])))
    write_text(paths["server"], patch_server_h(read_text(paths["server"])))
    write_text(paths["afpsl"], patch_afpsl_h(read_text(paths["afpsl"])))
    write_text(paths["stateless"], patch_stateless(read_text(paths["stateless"])))
    write_text(paths["commands"], patch_commands(read_text(paths["commands"])))
    write_text(paths["cmdline"], patch_cmdline(cmd_text))

    print("Applied known data-fork open R7G")
    print("  healthy known-size data open skips AFP2 pre-open parameter query")
    print("  parent DID still comes from R7C cache")
    print("  FPOpenFork/read/close semantics unchanged")
    print("  recovery retry uses conservative normal open")
    print("  R7F metadata reuse and R7E empty-fork skip retained")
    print("  resource-fork open path unchanged")
    print("  ATP/ASP transport unchanged")


if __name__ == "__main__":
    main()
