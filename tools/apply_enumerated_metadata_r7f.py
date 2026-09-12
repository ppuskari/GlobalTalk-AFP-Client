#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7F: consume richer FPEnumerate metadata.
#
# Healthy recursive file copies reuse FinderInfo and resource-fork length from
# the directory enumeration.  Recovery deliberately falls back to fresh
# metadata queries after R7D rebuilds the DID chain.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK ENUMERATED METADATA R7F"
R7E_MARKER = "GLOBALTALK ZERO DATAFORK SKIP R7E"


def die(msg):
    raise SystemExit("apply_enumerated_metadata_r7f: " + msg)


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


def patch_afpsl_header(text):
    if MARKER in text:
        return text

    old = '''struct afp_file_info_basic {
    char name[AFP_MAX_PATH];
    unsigned int creation_date;
    unsigned int modification_date;
    struct afp_unixprivs unixprivs;
    unsigned long long size;
};
'''
    new = '''/* GLOBALTALK ENUMERATED METADATA R7F */
#define AFP_SL_ENUM_FINDERINFO_VALID       0x00000001U
#define AFP_SL_ENUM_RESOURCE_SIZE_VALID    0x00000002U
#define AFP_SL_ENUM_NO_GENERIC_XATTRS      0x00000004U

struct afp_file_info_basic {
    char name[AFP_MAX_PATH];
    unsigned int creation_date;
    unsigned int modification_date;
    struct afp_unixprivs unixprivs;
    unsigned long long size;
    unsigned long long resource_size;
    unsigned int metadata_flags;
    unsigned char finderinfo[32];
};
'''
    text = replace_once(text, old, new, "afp_file_info_basic extension")

    old = '''int afp_sl_metadata_copy_remote_to_local(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode local_mode,
    unsigned int *warnings);
'''
    new = old + '''/* GLOBALTALK ENUMERATED METADATA R7F */
int afp_sl_metadata_copy_remote_to_local_known(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode local_mode,
    const unsigned char finderinfo[32],
    unsigned long long resource_size, unsigned int metadata_flags,
    unsigned int *warnings);
'''
    return replace_once(text, old, new, "known metadata prototype")


def patch_lowlevel(text):
    start, end = function_span(text, "int ll_readdir(")
    func = text[start:end]
    old = '''    if (volume->server->using_version->av_number < 30) {
        filebitmap |= (resource ?
                  kFPRsrcForkLenBit : kFPDataForkLenBit);
    } else {
        filebitmap |= (resource ?
                  kFPRsrcForkLenBit : kFPExtDataForkLenBit);
    }
'''
    if old not in func:
        old = '''    if (volume->server->using_version->av_number < 30) {
        filebitmap |= (resource ? kFPRsrcForkLenBit : kFPDataForkLenBit);
    } else {
        filebitmap |= (resource ? kFPRsrcForkLenBit : kFPExtDataForkLenBit);
    }
'''
    new = '''    /* GLOBALTALK ENUMERATED METADATA R7F */
    (void)resource;
    filebitmap |= kFPFinderInfoBit;
    if (volume->server->using_version->av_number < 30) {
        filebitmap |= kFPDataForkLenBit | kFPRsrcForkLenBit;
    } else {
        filebitmap |= kFPExtDataForkLenBit | kFPExtRsrcForkLenBit;
    }
'''
    if old not in func:
        die("ll_readdir fork bitmap block not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_commands(text):
    start, end = function_span(text, "static unsigned char process_readdir(")
    func = text[start:end]

    old = '''        size_t entry_size = sizeof(uint32_t) + name_len +
                            sizeof(uint32_t) * 2 +
                            sizeof(struct afp_unixprivs) +
                            sizeof(uint64_t);
'''
    new = '''        size_t entry_size = sizeof(uint32_t) + name_len +
                            sizeof(uint32_t) * 2 +
                            sizeof(struct afp_unixprivs) +
                            sizeof(uint64_t) * 2 +
                            sizeof(uint32_t) + 32U;
'''
    if old not in func:
        die("process_readdir entry-size block not found")
    func = func.replace(old, new, 1)

    old = '''        memcpy(p, &fp->size, sizeof(uint64_t));
        p += sizeof(uint64_t);
        fp = fp->next;
'''
    new = '''        memcpy(p, &fp->size, sizeof(uint64_t));
        p += sizeof(uint64_t);
        memcpy(p, &fp->resourcesize, sizeof(uint64_t));
        p += sizeof(uint64_t);
        {
            uint32_t r7f_flags =
                AFP_SL_ENUM_FINDERINFO_VALID |
                AFP_SL_ENUM_RESOURCE_SIZE_VALID;
            if (!v->server->using_version ||
                    v->server->using_version->av_number < 32) {
                r7f_flags |= AFP_SL_ENUM_NO_GENERIC_XATTRS;
            }
            memcpy(p, &r7f_flags, sizeof(r7f_flags));
            p += sizeof(r7f_flags);
        }
        memcpy(p, fp->finderinfo, 32U);
        p += 32U;
        fp = fp->next;
'''
    if old not in func:
        die("process_readdir packing tail not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_stateless(text):
    start, end = function_span(text, "int afp_sl_readdir(")
    func = text[start:end]
    old = '''                memcpy(&current_basic->size, p, sizeof(uint64_t));
                p += sizeof(uint64_t);
                current_basic++;
'''
    new = '''                memcpy(&current_basic->size, p, sizeof(uint64_t));
                p += sizeof(uint64_t);
                memcpy(&current_basic->resource_size, p, sizeof(uint64_t));
                p += sizeof(uint64_t);
                memcpy(&current_basic->metadata_flags, p, sizeof(uint32_t));
                p += sizeof(uint32_t);
                memcpy(current_basic->finderinfo, p, 32U);
                p += 32U;
                current_basic++;
'''
    if old not in func:
        die("afp_sl_readdir unpacking tail not found")
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def patch_metadata(text):
    if "int afp_sl_metadata_copy_remote_to_local_known(" in text:
        return text

    start, end = function_span(text, "int afp_sl_metadata_copy_remote_to_local(")
    helper = r'''

/* GLOBALTALK ENUMERATED METADATA R7F */
int afp_sl_metadata_copy_remote_to_local_known(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode mode,
    const unsigned char finderinfo[32],
    unsigned long long resource_size, unsigned int metadata_flags,
    unsigned int *warnings)
{
    static const unsigned char empty_finderinfo[32] = {0};
    unsigned char fetched_finderinfo[32];
    const unsigned char *use_finderinfo = finderinfo;
    int finder_ret;
    int ret;

    if (warnings) {
        *warnings = AFP_METADATA_WARNING_NONE;
    }

    if (!source_volume || !*source_volume || !source_path || !local_path
            || !metadata_mode_valid(mode)) {
        return -EINVAL;
    }

    if (mode == AFP_METADATA_NONE) {
        return 0;
    }

    if (metadata_flags & AFP_SL_ENUM_FINDERINFO_VALID) {
        if (!finderinfo) {
            return -EINVAL;
        }
        finder_ret = memcmp(finderinfo, empty_finderinfo,
                            sizeof(empty_finderinfo)) == 0
                     ? -ENOATTR : 32;
    } else {
        finder_ret = afp_sl_getfinderinfo(source_volume, source_path,
                                          fetched_finderinfo,
                                          sizeof(fetched_finderinfo));
        use_finderinfo = fetched_finderinfo;
    }

    if (finder_ret >= 0 && finder_ret != 32) {
        return -EIO;
    }

    if (finder_ret < 0 && !transfer_error_absent(finder_ret)
            && !transfer_error_unsupported(finder_ret)) {
        return finder_ret;
    }

    ret = afp_metadata_clear_local(local_path, mode, warnings);
    if (ret < 0) {
        return ret;
    }

    if (finder_ret == 32) {
        ret = local_finderinfo_set(local_path, mode, use_finderinfo);
    } else {
        ret = finder_ret;
    }

    ret = transfer_metadata_result(ret, warnings);
    if (ret < 0) {
        return ret;
    }

    if (!(metadata_flags & AFP_SL_ENUM_RESOURCE_SIZE_VALID)) {
        ret = afp_sl_getresourcefork(source_volume, source_path, NULL, 0, 0);
        if (ret > 0) {
            resource_size = (unsigned int)ret;
        } else if (ret < 0) {
            ret = transfer_metadata_result(ret, warnings);
            if (ret < 0) {
                return ret;
            }
            resource_size = 0;
        } else {
            resource_size = 0;
        }
    }

    if (resource_size > 0) {
        ret = stream_remote_resourcefork_to_local(source_volume, source_path,
                local_path, mode, resource_size, warnings);
        if (ret < 0) {
            return ret;
        }
    }

    if (metadata_flags & AFP_SL_ENUM_NO_GENERIC_XATTRS) {
        return 0;
    }

    return transfer_remote_xattrs_to_local(source_volume, source_path,
                                           local_path, mode, warnings);
}
'''
    return text[:end] + helper + text[end:]


def patch_cmdline(text):
    if "static int copy_remote_metadata_to_local_r7f(" not in text:
        start, end = function_span(text, "static int copy_remote_metadata_to_local(")
        helper = r'''

/* GLOBALTALK ENUMERATED METADATA R7F */
static int copy_remote_metadata_to_local_r7f(
        const char *remote_path, const char *local_path,
        const struct stat *st, const struct afp_file_info_basic *entry)
{
    unsigned int warnings = 0;
    int ret;
    int attempt = 0;

retry_remote_metadata:
    warnings = 0;
    if (attempt == 0 && entry) {
        ret = afp_sl_metadata_copy_remote_to_local_known(
                  &vol_id, remote_path, local_path, transfer_metadata_mode,
                  entry->finderinfo, entry->resource_size,
                  entry->metadata_flags, &warnings);
    } else {
        ret = afp_sl_metadata_copy_remote_to_local(
                  &vol_id, remote_path, local_path,
                  transfer_metadata_mode, &warnings);
    }
    metadata_warn(warnings);

    if (ret < 0) {
        int recover_ret;

        printf("R7F: remote metadata copy failed path=%s ret=%d warnings=%u attempt=%d\n",
               remote_path, ret, warnings, attempt + 1);

        if (attempt == 0) {
            int prime_ret;
            printf("R7F: metadata recovery requested path=%s ret=%d\n",
                   remote_path, ret);
            recover_ret = recover_session(1, 1);
            printf("R7F: metadata recovery result path=%s ret=%d\n",
                   remote_path, recover_ret);

            if (recover_ret == 0) {
                prime_ret = r7d_prime_parent_did_chain(remote_path);
                printf("R7F: metadata recovery DID-prime path=%s ret=%d\n",
                       remote_path, prime_ret);
                if (prime_ret != 0) {
                    return prime_ret;
                }
                attempt = 1;
                printf("R7F: retrying metadata with fresh post-recovery lookup path=%s\n",
                       remote_path);
                goto retry_remote_metadata;
            }
        }

        return ret;
    }

    if (chmod(local_path, st->st_mode & 07777) < 0) {
        int saved_errno = errno;
        if (saved_errno != EPERM) {
            return -saved_errno;
        }
    }

    {
        struct timespec times[2] = {
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
            { .tv_sec = st->st_mtime, .tv_nsec = 0 },
        };
        if (utimensat(AT_FDCWD, local_path, times, 0) < 0) {
            return -errno;
        }
    }

    return 0;
}
'''
        text = text[:end] + helper + text[end:]

    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]
    old = '''            if (copy_remote_metadata_to_local(new_server_path, new_local_path,
                                              &st) < 0) {
'''
    new = '''            if (copy_remote_metadata_to_local_r7f(
                    new_server_path, new_local_path, &st, p) < 0) {
'''
    count = func.count(old)
    if count != 1:
        die("recursive file metadata call: expected once, found {}".format(count))
    func = func.replace(old, new, 1)
    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_enumerated_metadata_r7f.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    paths = {
        "afpsl": os.path.join(root, "include", "afpsl.h"),
        "lowlevel": os.path.join(root, "lib", "lowlevel.c"),
        "commands": os.path.join(root, "daemon", "commands.c"),
        "stateless": os.path.join(root, "daemon", "stateless.c"),
        "metadata": os.path.join(root, "daemon", "metadata.c"),
        "cmdline": os.path.join(root, "cmdline", "cmdline_afp.c"),
    }

    for path in paths.values():
        if not os.path.isfile(path):
            die("missing {}".format(path))

    cmd_text = read_text(paths["cmdline"])
    if R7E_MARKER not in cmd_text:
        die("R7E must be applied first")

    header = read_text(paths["afpsl"])
    if MARKER in header:
        print("Enumerated metadata R7F already applied: {}".format(root))
        return

    write_text(paths["afpsl"], patch_afpsl_header(header))
    write_text(paths["lowlevel"], patch_lowlevel(read_text(paths["lowlevel"])))
    write_text(paths["commands"], patch_commands(read_text(paths["commands"])))
    write_text(paths["stateless"], patch_stateless(read_text(paths["stateless"])))
    write_text(paths["metadata"], patch_metadata(read_text(paths["metadata"])))
    write_text(paths["cmdline"], patch_cmdline(cmd_text))

    print("Applied enumerated metadata R7F")
    print("  FPEnumerate requests FinderInfo + both fork lengths")
    print("  recursive metadata reuses FinderInfo and resource-fork length")
    print("  AFP < 3.2 skips generic xattr enumeration")
    print("  recovery retry uses fresh legacy metadata queries")
    print("  R7E empty data-fork skip retained")
    print("  ATP/ASP transport and read sizing unchanged")


if __name__ == "__main__":
    main()
