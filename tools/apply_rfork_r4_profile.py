#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Profile-only timing overlay for the R4 stateful resource-fork stream.
# Apply after apply_rfork_r4_stream.py.  This does not change read sizes,
# AFP/ASP behavior, fork lifetime, or local metadata semantics.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK RFORK R4 PROFILE"


def die(msg):
    raise SystemExit("apply_rfork_r4_profile: " + msg)


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


PROFILED_FUNCTION = r'''/* GLOBALTALK RFORK R4 PROFILE
 * Timing only: transport behavior is identical to R4. */
static long long r4p_elapsed_us(const struct timeval *start,
                                const struct timeval *end)
{
    return ((long long)end->tv_sec - (long long)start->tv_sec) * 1000000LL
           + ((long long)end->tv_usec - (long long)start->tv_usec);
}

static int stream_remote_resourcefork_to_local(
    volumeid_t *source_volume, const char *source_path,
    const char *local_path, enum afp_metadata_mode mode,
    unsigned long long total, unsigned int *warnings)
{
    unsigned char *buffer = NULL;
    unsigned long long offset = 0;
    unsigned int fileid = 0;
    int opened = 0;
    int ret = 0;
    struct timeval total_start, total_end;
    struct timeval open_end, close_start;
    struct timeval phase_start, phase_end;
    long long read_us = 0;
    long long write_us = 0;
    long long open_us = 0;
    long long close_us = 0;
    long long total_us;
    long long other_us;

    gettimeofday(&total_start, NULL);

    buffer = malloc(R4_RESOURCE_STREAM_CHUNK);
    if (!buffer) {
        return -ENOMEM;
    }

    ret = afp_sl_open_resourcefork(source_volume, source_path, NULL,
                                   &fileid, O_RDONLY);
    gettimeofday(&open_end, NULL);
    open_us = r4p_elapsed_us(&total_start, &open_end);
    if (ret < 0) {
        free(buffer);
        return ret;
    }
    opened = 1;

    while (offset < total) {
        unsigned long long remaining = total - offset;
        unsigned int chunk = R4_RESOURCE_STREAM_CHUNK;
        unsigned int received = 0;
        unsigned int eof = 0;
        int write_ret;

        if (remaining < chunk) {
            chunk = (unsigned int)remaining;
        }

        gettimeofday(&phase_start, NULL);
        ret = afp_sl_read(source_volume, fileid, 1, offset, chunk,
                          &received, &eof, (char *)buffer);
        gettimeofday(&phase_end, NULL);
        read_us += r4p_elapsed_us(&phase_start, &phase_end);

        if (ret != 0) {
            goto done;
        }
        if (received == 0 || received > chunk) {
            ret = -EIO;
            goto done;
        }

        gettimeofday(&phase_start, NULL);
        write_ret = local_resourcefork_write(local_path, mode, buffer,
                                              received, (off_t)offset);
        gettimeofday(&phase_end, NULL);
        write_us += r4p_elapsed_us(&phase_start, &phase_end);

        if (transfer_error_unsupported(write_ret)) {
            transfer_warning(warnings, AFP_METADATA_WARNING_UNSUPPORTED);
            ret = 0;
            goto done;
        }
        if (write_ret < 0) {
            ret = write_ret;
            goto done;
        }

        offset += received;
        if (eof && offset < total) {
            ret = -EIO;
            goto done;
        }
    }

done:
    gettimeofday(&close_start, NULL);
    if (opened) {
        int close_ret = afp_sl_close(source_volume, fileid);
        if (ret == 0 && close_ret < 0) {
            ret = close_ret;
        }
    }
    gettimeofday(&total_end, NULL);
    close_us = r4p_elapsed_us(&close_start, &total_end);
    total_us = r4p_elapsed_us(&total_start, &total_end);
    other_us = total_us - open_us - read_us - write_us - close_us;
    if (other_us < 0) {
        other_us = 0;
    }

    if (total_us > 0) {
        fprintf(stderr,
                "R4PROFILE resource=%llu bytes total=%.3fs rate=%.2f kbit/s "
                "open=%.3fs read=%.3fs write=%.3fs close=%.3fs other=%.3fs\\n",
                offset,
                total_us / 1000000.0,
                offset * 8.0 / (total_us / 1000000.0) / 1000.0,
                open_us / 1000000.0,
                read_us / 1000000.0,
                write_us / 1000000.0,
                close_us / 1000000.0,
                other_us / 1000000.0);
    }

    free(buffer);
    return ret;
}
'''


def main():
    if len(sys.argv) != 2:
        die("usage: apply_rfork_r4_profile.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "daemon", "metadata.c")
    if not os.path.isfile(path):
        die("required source missing: {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("R4 profile timing already present: {}".format(path))
        return

    if "GLOBALTALK RFORK R4 STATEFUL STREAM" not in text:
        die("R4 stream overlay must be applied first")

    if "#include <sys/time.h>" not in text:
        guard = "#include <sys/stat.h>\n"
        if guard not in text:
            die("sys/stat.h include guard not found")
        text = text.replace(guard, guard + "#include <sys/time.h>\n", 1)

    start, end = function_span(text,
        "static int stream_remote_resourcefork_to_local(")
    text = text[:start] + PROFILED_FUNCTION + text[end:]
    write_text(path, text)

    print("R4 profile timing ready: {}".format(path))
    print("  transport/read sizes unchanged from R4")


if __name__ == "__main__":
    main()
