#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP Client R7S: LocalTalk endurance mode.
#
# Layered after Stable R7Q + R7R.  This is intentionally recovery-only:
# - the six-cycle data recovery budget is consecutive/no-progress, not a
#   lifetime cap for a multi-hour file;
# - verified CNID+size checkpoints allow safe cross-process resume;
# - an unrecovered file is deferred so the first tree pass can continue;
# - deferred files receive at most five fresh-session retry passes.
#
# Healthy AFP request sizing, ATP timing, pacing, metadata semantics and
# R7I.2 identity requirements remain unchanged.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import io
import os
import sys

MARKER = "GLOBALTALK LOCALTALK ENDURANCE R7S"


def die(msg):
    raise SystemExit("apply_localtalk_endurance_r7s: " + msg)


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


BASE_HELPERS = r'''
/* GLOBALTALK LOCALTALK ENDURANCE R7S
 * Persistent resume state is stored outside the downloaded tree.  The Python
 * launcher creates GT_AFP_R7S_STATE_DIR, keyed by remote URL + destination.
 * Every state record is additionally keyed by the remote and local paths and
 * is accepted only when nonzero AFP CNID + exact data-fork size still match.
 */
#define R7S_CHECKPOINT_GRANULARITY (512ULL * 1024ULL)
#define R7S_DEFERRED_PASSES 5

struct r7s_deferred_file {
    char remote[AFP_MAX_PATH];
    char local[PATH_MAX];
    struct stat expected;
    int resolved;
    int permanent;
};

static struct r7s_deferred_file *r7s_deferred = NULL;
static size_t r7s_deferred_count = 0;
static size_t r7s_deferred_cap = 0;
static int r7s_deferred_mode = 0;

static unsigned long long r7s_hash_update(unsigned long long h,
        const unsigned char *data, size_t length)
{
    size_t i;
    for (i = 0; i < length; i++) {
        h ^= (unsigned long long)data[i];
        h *= 1099511628211ULL;
    }
    return h;
}

static unsigned long long r7s_hash_text(const char *text)
{
    unsigned long long h = 14695981039346656037ULL;
    if (text) {
        h = r7s_hash_update(h, (const unsigned char *)text, strlen(text));
    }
    return h;
}

static int r7s_state_path(const char *remote_path, const char *local_path,
                          char *out, size_t out_size)
{
    const char *dir = getenv("GT_AFP_R7S_STATE_DIR");
    unsigned long long h;
    int n;

    if (!dir || !*dir || !remote_path || !local_path || !out || out_size == 0) {
        return 0;
    }

    h = r7s_hash_text(remote_path);
    h = r7s_hash_update(h, (const unsigned char *)"\xff", 1);
    h = r7s_hash_update(h, (const unsigned char *)local_path, strlen(local_path));
    n = snprintf(out, out_size, "%s/%016llx.state", dir, h);
    if (n < 0 || (size_t)n >= out_size) {
        return -ENAMETOOLONG;
    }
    return 1;
}

/* Return 1 for a valid checkpoint, 0 when no state exists, and -1 when state
 * exists but is stale/corrupt.  A stale state deliberately disables the older
 * size+mtime shortcut for that object. */
static int r7s_checkpoint_load(const char *remote_path, const char *local_path,
                               const struct stat *remote,
                               unsigned long long *offset, int *complete)
{
    char state_path[PATH_MAX];
    char magic[8];
    FILE *f;
    struct stat local;
    unsigned long long cnid = 0;
    unsigned long long size = 0;
    unsigned long long saved_offset = 0;
    unsigned long long remote_hash = 0;
    unsigned long long local_hash = 0;
    int saved_complete = 0;
    int path_ret;

    if (!remote || !offset || !complete) {
        return -1;
    }
    *offset = 0;
    *complete = 0;

    path_ret = r7s_state_path(remote_path, local_path,
                              state_path, sizeof(state_path));
    if (path_ret <= 0) {
        return path_ret;
    }

    f = fopen(state_path, "r");
    if (!f) {
        return errno == ENOENT ? 0 : -1;
    }

    if (fscanf(f, "%7s %llu %llu %llu %d %llx %llx",
               magic, &cnid, &size, &saved_offset, &saved_complete,
               &remote_hash, &local_hash) != 7) {
        fclose(f);
        return -1;
    }
    fclose(f);

    if (strcmp(magic, "R7S1") != 0
            || remote->st_ino == 0
            || cnid != (unsigned long long)remote->st_ino
            || size != (unsigned long long)remote->st_size
            || remote_hash != r7s_hash_text(remote_path)
            || local_hash != r7s_hash_text(local_path)
            || saved_offset > size) {
        return -1;
    }

    if (lstat(local_path, &local) < 0 || !S_ISREG(local.st_mode)
            || (unsigned long long)local.st_size < saved_offset) {
        return -1;
    }
    if (saved_complete && (unsigned long long)local.st_size != size) {
        return -1;
    }

    *offset = saved_offset;
    *complete = saved_complete ? 1 : 0;
    return 1;
}

static int r7s_checkpoint_save(const char *remote_path, const char *local_path,
                               const struct stat *remote,
                               unsigned long long offset, int complete,
                               int data_fd)
{
    char state_path[PATH_MAX];
    char temp_path[PATH_MAX];
    FILE *f;
    int n;
    int path_ret;

    if (!remote || remote->st_ino == 0 || !remote_path || !local_path) {
        return 0;
    }
    if (offset > (unsigned long long)remote->st_size) {
        return -EINVAL;
    }

    path_ret = r7s_state_path(remote_path, local_path,
                              state_path, sizeof(state_path));
    if (path_ret <= 0) {
        return path_ret;
    }

    /* Never publish a checkpoint ahead of data known durable locally. */
    if (data_fd >= 0 && fdatasync(data_fd) < 0) {
        return -errno;
    }

    n = snprintf(temp_path, sizeof(temp_path), "%s.tmp.%ld",
                 state_path, (long)getpid());
    if (n < 0 || (size_t)n >= sizeof(temp_path)) {
        return -ENAMETOOLONG;
    }

    f = fopen(temp_path, "w");
    if (!f) {
        return -errno;
    }

    if (fprintf(f, "R7S1 %llu %llu %llu %d %016llx %016llx\n",
                (unsigned long long)remote->st_ino,
                (unsigned long long)remote->st_size,
                offset, complete ? 1 : 0,
                r7s_hash_text(remote_path), r7s_hash_text(local_path)) < 0
            || fflush(f) != 0 || fsync(fileno(f)) != 0) {
        int saved = errno ? errno : EIO;
        fclose(f);
        unlink(temp_path);
        return -saved;
    }

    if (fclose(f) != 0) {
        int saved = errno ? errno : EIO;
        unlink(temp_path);
        return -saved;
    }
    if (rename(temp_path, state_path) < 0) {
        int saved = errno;
        unlink(temp_path);
        return -saved;
    }
    return 0;
}

static void r7s_deferred_reset(void)
{
    free(r7s_deferred);
    r7s_deferred = NULL;
    r7s_deferred_count = 0;
    r7s_deferred_cap = 0;
}

static int r7s_defer_file(const char *remote_path, const char *local_path,
                          const struct stat *expected)
{
    size_t i;
    struct r7s_deferred_file *grown;

    if (!remote_path || !local_path || !expected) {
        return -EINVAL;
    }

    for (i = 0; i < r7s_deferred_count; i++) {
        if (strcmp(r7s_deferred[i].remote, remote_path) == 0
                && strcmp(r7s_deferred[i].local, local_path) == 0) {
            r7s_deferred[i].expected = *expected;
            r7s_deferred[i].resolved = 0;
            return 0;
        }
    }

    if (r7s_deferred_count == r7s_deferred_cap) {
        size_t next_cap = r7s_deferred_cap ? r7s_deferred_cap * 2U : 16U;
        grown = realloc(r7s_deferred, next_cap * sizeof(*r7s_deferred));
        if (!grown) {
            return -ENOMEM;
        }
        r7s_deferred = grown;
        r7s_deferred_cap = next_cap;
    }

    memset(&r7s_deferred[r7s_deferred_count], 0,
           sizeof(r7s_deferred[r7s_deferred_count]));
    if (strlcpy(r7s_deferred[r7s_deferred_count].remote, remote_path,
                sizeof(r7s_deferred[r7s_deferred_count].remote))
            >= sizeof(r7s_deferred[r7s_deferred_count].remote)
            || strlcpy(r7s_deferred[r7s_deferred_count].local, local_path,
                       sizeof(r7s_deferred[r7s_deferred_count].local))
            >= sizeof(r7s_deferred[r7s_deferred_count].local)) {
        return -ENAMETOOLONG;
    }
    r7s_deferred[r7s_deferred_count].expected = *expected;
    r7s_deferred_count++;
    return 0;
}

/* End-of-pass retries deliberately do not use afp_sl_resume().  Tear down the
 * current server session and force afp_sl_connect() so each pass gets a fresh
 * AFP/ASP session. */
static int r7s_fresh_reopen_session(void)
{
    char mesg[MAX_ERROR_LEN];
    char saved_volume[AFP_VOLUME_NAME_LEN];
    char saved_dir[AFP_MAX_PATH];
    struct afp_url reconnect_url;
    serverid_t new_server_id = NULL;
    volumeid_t new_vol_id = NULL;
    unsigned int uam_mask;
    int ret;

    memset(mesg, 0, sizeof(mesg));
    strlcpy(saved_volume, url.volumename, sizeof(saved_volume));
    strlcpy(saved_dir, curdir, sizeof(saved_dir));
    reconnect_url = url;
    if (connect_servername[0] != '\0') {
        strlcpy(reconnect_url.servername, connect_servername,
                sizeof(reconnect_url.servername));
    }
    uam_mask = get_uam_mask_for_url();
    if (uam_mask == 0) {
        return -1;
    }

    if (vol_id) {
        (void)afp_sl_detach(&vol_id, NULL);
        vol_id = NULL;
    }
    if (server_id) {
        if (afp_sl_disconnect(&server_id) != 0) {
            afp_sl_exit();
        }
        server_id = NULL;
    }
    connected = 0;

    sleep(1);
    ret = afp_sl_connect(&reconnect_url, uam_mask, &new_server_id, mesg);
    if (ret != 0) {
        printf("R7S: fresh-session connect failed ret=%d detail=%s\n",
               ret, mesg[0] ? mesg : "-");
        return -1;
    }

    if (saved_volume[0] != '\0') {
        strlcpy(url.volumename, saved_volume, sizeof(url.volumename));
        ret = attach_volume_with_password_prompt(new_server_id, &new_vol_id,
              VOLUME_EXTRA_FLAGS_NO_LOCKING);
        if (ret != 0) {
            printf("R7S: fresh-session volume attach failed ret=%d\n", ret);
            afp_sl_disconnect(&new_server_id);
            return -1;
        }
    }

    server_id = new_server_id;
    vol_id = new_vol_id;
    connected = 1;
    if (saved_dir[0] != '\0') {
        strlcpy(curdir, saved_dir, sizeof(curdir));
    }
    return 0;
}

'''


RETRY_HELPER = r'''
/* GLOBALTALK LOCALTALK ENDURANCE R7S - deferred-file second pass */
static int r7s_retry_deferred_files(unsigned long long *bytes_transferred)
{
    int pass;

    for (pass = 1; pass <= R7S_DEFERRED_PASSES && r7s_deferred_count; pass++) {
        size_t i;
        size_t write_index = 0;

        printf("R7S: deferred pass=%d/%d files=%llu fresh-session=open\n",
               pass, R7S_DEFERRED_PASSES,
               (unsigned long long)r7s_deferred_count);

        if (r7s_fresh_reopen_session() != 0) {
            printf("R7S: deferred pass=%d/%d fresh-session failed\n",
                   pass, R7S_DEFERRED_PASSES);
            sleep(1);
            continue;
        }

        for (i = 0; i < r7s_deferred_count; i++) {
            struct r7s_deferred_file item = r7s_deferred[i];
            struct stat fresh;
            unsigned long long resume_offset = 0;
            unsigned long long amount = 0;
            int state_complete = 0;
            int state_ret;
            int fd = -1;
            int file_ret = -1;

            if (item.permanent) {
                r7s_deferred[write_index++] = item;
                continue;
            }

            if (r7d_prime_parent_did_chain(item.remote) != 0) {
                printf("R7S: deferred DID-prime failed path=%s pass=%d/%d\n",
                       item.remote, pass, R7S_DEFERRED_PASSES);
                r7s_deferred[write_index++] = item;
                continue;
            }

            memset(&fresh, 0, sizeof(fresh));
            if (afp_sl_stat(&vol_id, item.remote, NULL, &fresh) != 0) {
                printf("R7S: deferred validation stat failed path=%s pass=%d/%d\n",
                       item.remote, pass, R7S_DEFERRED_PASSES);
                r7s_deferred[write_index++] = item;
                continue;
            }

            if (item.expected.st_ino == 0 || fresh.st_ino == 0
                    || fresh.st_ino != item.expected.st_ino
                    || fresh.st_size != item.expected.st_size) {
                printf("R7S: deferred identity mismatch path=%s "
                       "expected-cnid=%llu fresh-cnid=%llu "
                       "expected-size=%llu fresh-size=%llu\n",
                       item.remote,
                       (unsigned long long)item.expected.st_ino,
                       (unsigned long long)fresh.st_ino,
                       (unsigned long long)item.expected.st_size,
                       (unsigned long long)fresh.st_size);
                item.permanent = 1;
                r7s_deferred[write_index++] = item;
                continue;
            }

            state_ret = r7s_checkpoint_load(item.remote, item.local, &fresh,
                                            &resume_offset, &state_complete);
            if (state_ret > 0 && state_complete) {
                printf("R7S: deferred data already complete path=%s size=%llu\n",
                       item.remote, (unsigned long long)fresh.st_size);
                file_ret = 0;
            } else {
                if (state_ret <= 0) {
                    resume_offset = 0;
                }

                if (resume_offset > 0) {
                    fd = open(item.local, O_RDWR);
                    if (fd >= 0
                            && (ftruncate(fd, (off_t)resume_offset) != 0
                                || lseek(fd, (off_t)resume_offset, SEEK_SET) < 0)) {
                        close(fd);
                        fd = -1;
                    }
                }
                if (fd < 0) {
                    resume_offset = 0;
                    fd = open(item.local, O_CREAT | O_TRUNC | O_RDWR, 0644);
                }
                if (fd < 0) {
                    printf("R7S: deferred local open failed path=%s errno=%d\n",
                           item.local, errno);
                    r7s_deferred[write_index++] = item;
                    continue;
                }

                printf("R7S: deferred retry path=%s pass=%d/%d offset=%llu\n",
                       item.remote, pass, R7S_DEFERRED_PASSES, resume_offset);
                r7s_deferred_mode = 1;
                file_ret = retrieve_file(item.remote, fd, &fresh, &amount,
                                         item.local, resume_offset);
                r7s_deferred_mode = 0;
                close(fd);
                fd = -1;
                if (file_ret == 0 && bytes_transferred) {
                    *bytes_transferred += amount;
                }
            }

            if (file_ret == 0
                    && copy_remote_metadata_to_local(item.remote, item.local,
                                                     &fresh) == 0) {
                (void)r7s_checkpoint_save(item.remote, item.local, &fresh,
                                          (unsigned long long)fresh.st_size,
                                          1, -1);
                printf("R7S: deferred resolved path=%s pass=%d/%d\n",
                       item.remote, pass, R7S_DEFERRED_PASSES);
                continue;
            }

            r7s_deferred[write_index++] = item;
        }

        r7s_deferred_count = write_index;
        if (r7s_deferred_count == 0) {
            printf("R7S: all deferred files resolved\n");
            return 0;
        }
        sleep(1);
    }

    if (r7s_deferred_count) {
        size_t i;
        printf("R7S: deferred retry limit exhausted unresolved=%llu passes=%d\n",
               (unsigned long long)r7s_deferred_count, R7S_DEFERRED_PASSES);
        for (i = 0; i < r7s_deferred_count; i++) {
            printf("R7S: unresolved path=%s\n", r7s_deferred[i].remote);
        }
        return -1;
    }
    return 0;
}

'''


def insert_helpers(text):
    sig = "static int retrieve_file("
    pos = text.find(sig)
    if pos < 0:
        die("retrieve_file insertion point missing")
    text = text[:pos] + BASE_HELPERS + text[pos:]

    sig2 = "static int download_directory("
    pos2 = text.find(sig2)
    if pos2 < 0:
        die("download_directory insertion point missing")
    return text[:pos2] + RETRY_HELPER + text[pos2:]


def patch_retrieve(text):
    start, end = function_span(text, "static int retrieve_file(")
    func = text[start:end]

    func = replace_once(
        func,
        "static int retrieve_file(char * arg, int fd, struct stat *stat,\n"
        "                         unsigned long long *amount_written)\n",
        "static int retrieve_file(char * arg, int fd, struct stat *stat,\n"
        "                         unsigned long long *amount_written,\n"
        "                         const char *local_path,\n"
        "                         unsigned long long initial_offset)\n",
        "retrieve signature")

    func = replace_once(
        func,
        "    unsigned long long total = 0;\n",
        "    unsigned long long total = initial_offset;\n"
        "    const unsigned long long r7s_start_total = initial_offset;\n"
        "    unsigned long long r7s_last_checkpoint = initial_offset;\n",
        "initial resume offset")

    func = replace_once(
        func,
        "    const int max_recoveries = 6;\n",
        "    const int max_recoveries = r7s_deferred_mode ? 1 : 6;\n",
        "consecutive recovery budget")

    func = replace_once(
        func,
        "    expected_stat = *stat;\n\n",
        "    expected_stat = *stat;\n"
        "    if (initial_offset > (unsigned long long)expected_stat.st_size) {\n"
        "        op_ret = -ESTALE;\n"
        "        printf(\"R7S: checkpoint offset beyond remote size path=%s \"\n"
        "               \"offset=%llu size=%llu\\n\", path, initial_offset,\n"
        "               (unsigned long long)expected_stat.st_size);\n"
        "        goto out;\n"
        "    }\n"
        "    if (initial_offset > 0) {\n"
        "        printf(\"R7S: cross-process resume armed path=%s offset=%llu \"\n"
        "               \"size=%llu cnid=%llu\\n\", path, initial_offset,\n"
        "               (unsigned long long)expected_stat.st_size,\n"
        "               (unsigned long long)expected_stat.st_ino);\n"
        "    }\n\n",
        "resume validation insertion")

    telemetry = r'''        if (r7p_progress_enabled()) {
            printf("R7P: data path=%s delta=%u total=%llu expected=%llu\n",
                   path, received, total,
                   (unsigned long long)expected_stat.st_size);
            fflush(stdout);
        }
'''
    endurance = telemetry + r'''        /* R7S counts only consecutive/no-progress recovery failures.
         * One verified resumed data block ends the incident. */
        if (recoveries > 0) {
            printf("R7S: recovery incident cleared path=%s offset=%llu prior=%d/%d\n",
                   path, total, recoveries, max_recoveries);
            recoveries = 0;
        }
        if (local_path
                && total >= r7s_last_checkpoint + R7S_CHECKPOINT_GRANULARITY) {
            int checkpoint_ret = r7s_checkpoint_save(
                path, local_path, &expected_stat, total, 0, fd);
            if (checkpoint_ret == 0) {
                r7s_last_checkpoint = total;
            } else if (checkpoint_ret < 0) {
                printf("R7S: checkpoint write warning path=%s ret=%d\n",
                       path, checkpoint_ret);
            }
        }
'''
    func = replace_once(func, telemetry, endurance, "progress/reset checkpoint")

    success = "    *amount_written = total;\n    ret = 0;\n    goto out;\n"
    success_new = r'''    if (local_path) {
        int checkpoint_ret = r7s_checkpoint_save(
            path, local_path, &expected_stat, total, 1, fd);
        if (checkpoint_ret < 0) {
            printf("R7S: completed checkpoint warning path=%s ret=%d\n",
                   path, checkpoint_ret);
        }
    }
    *amount_written = total >= r7s_start_total
        ? total - r7s_start_total : 0;
    ret = 0;
    goto out;
'''
    func = replace_once(func, success, success_new, "complete checkpoint")

    out_anchor = "out:\n    *amount_written = total;\n"
    out_new = r'''out:
    if (ret != 0 && local_path && total > 0
            && total < (unsigned long long)expected_stat.st_size) {
        int checkpoint_ret = r7s_checkpoint_save(
            path, local_path, &expected_stat, total, 0, fd);
        if (checkpoint_ret < 0) {
            printf("R7S: partial checkpoint warning path=%s ret=%d\n",
                   path, checkpoint_ret);
        }
    }
    *amount_written = total >= r7s_start_total
        ? total - r7s_start_total : 0;
'''
    func = replace_once(func, out_anchor, out_new, "out delta/checkpoint")

    text = text[:start] + func + text[end:]

    text = replace_once(
        text,
        "retrieve_file(new_server_path, fd, &st, &amount)",
        "retrieve_file(new_server_path, fd, &st, &amount,\n"
        "                                  new_local_path, resume_offset)",
        "recursive retrieve call")
    text = replace_once(
        text,
        "retrieve_file(remote_path, fd, &st, &bytes_transferred)",
        "retrieve_file(remote_path, fd, &st, &bytes_transferred,\n"
        "                                    dest_path, 0)",
        "direct batch retrieve call")
    text = replace_once(
        text,
        "retrieve_file(filename, fd, &stat, total)",
        "retrieve_file(filename, fd, &stat, total, localfilename, 0)",
        "interactive get retrieve call")
    text = replace_once(
        text,
        "retrieve_file(filename, fileno(stdout), &stat, &amount_written)",
        "retrieve_file(filename, fileno(stdout), &stat, &amount_written, NULL, 0)",
        "cat retrieve call")
    return text


def patch_recursive(text):
    start, end = function_span(text, "static int download_directory(")
    func = text[start:end]

    func = replace_once(
        func,
        "            int fd = -1;\n",
        "            int fd = -1;\n"
        "            unsigned long long resume_offset = 0;\n"
        "            int r7s_state_complete = 0;\n"
        "            int r7s_state_ret = 0;\n",
        "R7Q recursive R7S locals")

    anchor = "            if (verbose_mode) {\n"
    search_from = func.find("local_ret = r7q_existing_local")
    if search_from < 0:
        die("R7Q existing-local call missing")
    pos = func.find(anchor, search_from)
    if pos < 0:
        die("R7Q verbose anchor after local check missing")
    state_block = r'''            r7s_state_ret = r7s_checkpoint_load(
                new_server_path, new_local_path, &st,
                &resume_offset, &r7s_state_complete);
            if (r7s_state_ret > 0 && r7s_state_complete) {
                local_match = 1;
                resume_offset = (unsigned long long)st.st_size;
                printf("R7S: completed checkpoint reuse path=%s size=%llu cnid=%llu\n",
                       new_server_path,
                       (unsigned long long)st.st_size,
                       (unsigned long long)st.st_ino);
            } else if (r7s_state_ret > 0 && resume_offset > 0) {
                local_match = 0;
                printf("R7S: resume-checkpoint path=%s offset=%llu size=%llu cnid=%llu\n",
                       new_server_path, resume_offset,
                       (unsigned long long)st.st_size,
                       (unsigned long long)st.st_ino);
            } else if (r7s_state_ret < 0) {
                local_match = 0;
                resume_offset = 0;
                printf("R7S: stale checkpoint ignored path=%s\n", new_server_path);
            }

'''
    func = func[:pos] + state_block + func[pos:]

    old_open = """                fd = open(new_local_path, O_CREAT | O_TRUNC | O_RDWR, 0644);\n                if (fd < 0) {\n                    perror(\"open\");\n                    ret = -1;\n                    break;\n                }\n\n"""
    new_open = r'''                if (r7s_state_ret > 0 && !r7s_state_complete
                        && resume_offset > 0) {
                    fd = open(new_local_path, O_RDWR);
                    if (fd >= 0
                            && (ftruncate(fd, (off_t)resume_offset) != 0
                                || lseek(fd, (off_t)resume_offset, SEEK_SET) < 0)) {
                        close(fd);
                        fd = -1;
                    }
                }
                if (fd < 0) {
                    resume_offset = 0;
                    fd = open(new_local_path, O_CREAT | O_TRUNC | O_RDWR, 0644);
                }
                if (fd < 0) {
                    perror("open");
                    ret = -1;
                    break;
                }

'''
    func = replace_once(func, old_open, new_open, "recursive checkpoint open")

    old_fail = """                    if (file_ret < 0) {\n                        ret = -1;\n                        break;\n                    }\n\n                    bytes += amount;\n"""
    new_fail = r'''                    if (file_ret < 0) {
                        if (r7s_defer_file(new_server_path, new_local_path, &st) == 0) {
                            int continue_ret;
                            printf("R7S: deferred file path=%s reason=data-fork\n",
                                   new_server_path);
                            continue_ret = recover_session(1, 1);
                            printf("R7S: continue-tree session recovery path=%s ret=%d\n",
                                   new_server_path, continue_ret);
                            if (continue_ret == 0) {
                                (void)r7d_prime_parent_did_chain(new_server_path);
                            }
                            continue;
                        }
                        ret = -1;
                        break;
                    }

                    bytes += amount;
'''
    func = replace_once(func, old_fail, new_fail, "defer data failure")

    old_meta = r'''            if (copy_remote_metadata_to_local(new_server_path, new_local_path,
                                              &st) < 0) {
                char display_remote[AFP_MAX_PATH * 4];
                printf("Could not preserve metadata for %s\n",
                       display_text(new_server_path, display_remote,
                                    sizeof(display_remote)));
                ret = -1;
                break;
            }
'''
    new_meta = r'''            if (copy_remote_metadata_to_local(new_server_path, new_local_path,
                                              &st) < 0) {
                char display_remote[AFP_MAX_PATH * 4];
                printf("Could not preserve metadata for %s\n",
                       display_text(new_server_path, display_remote,
                                    sizeof(display_remote)));
                (void)r7s_checkpoint_save(new_server_path, new_local_path, &st,
                                          (unsigned long long)st.st_size, 1, -1);
                if (r7s_defer_file(new_server_path, new_local_path, &st) == 0) {
                    int continue_ret;
                    printf("R7S: deferred file path=%s reason=metadata\n",
                           new_server_path);
                    continue_ret = recover_session(1, 1);
                    printf("R7S: continue-tree session recovery path=%s ret=%d\n",
                           new_server_path, continue_ret);
                    if (continue_ret == 0) {
                        (void)r7d_prime_parent_did_chain(new_server_path);
                    }
                    continue;
                }
                ret = -1;
                break;
            }
            if (local_match) {
                (void)r7s_checkpoint_save(new_server_path, new_local_path, &st,
                                          (unsigned long long)st.st_size, 1, -1);
            }
'''
    func = replace_once(func, old_meta, new_meta, "defer metadata failure")

    return text[:start] + func + text[end:]


def patch_batch_driver(text):
    start, end = function_span(text, "int cmdline_batch_transfer(")
    func = text[start:end]

    func = replace_once(
        func,
        "    metadata_warning_emitted = 0;\n",
        "    metadata_warning_emitted = 0;\n"
        "    r7s_deferred_reset();\n",
        "batch queue reset")

    func = replace_once(
        func,
        "            ret = download_directory(remote_path, local_path, &bytes_transferred);\n"
        "            goto out;\n",
        "            ret = download_directory(remote_path, local_path, &bytes_transferred);\n"
        "            if (r7s_deferred_count > 0) {\n"
        "                int deferred_ret = r7s_retry_deferred_files(&bytes_transferred);\n"
        "                if (deferred_ret != 0) {\n"
        "                    ret = -1;\n"
        "                }\n"
        "            }\n"
        "            goto out;\n",
        "end-of-pass deferred retry")

    return text[:start] + func + text[end:]


def main():
    if len(sys.argv) != 2:
        die("usage: apply_localtalk_endurance_r7s.py NETATALK_CLIENT_TREE")

    root = os.path.abspath(sys.argv[1])
    path = os.path.join(root, "cmdline", "cmdline_afp.c")
    if not os.path.isfile(path):
        die("missing {}".format(path))

    text = read_text(path)
    if MARKER in text:
        print("LocalTalk endurance R7S already applied: {}".format(path))
        return

    required = (
        "GLOBALTALK PROGRESS TELEMETRY R7P",
        "GLOBALTALK RETRY EXISTING R7Q",
        "GLOBALTALK RECOVERY DID MULTISLASH R7R",
        "GLOBALTALK DATAFORK RECOVERY LOOP R7L",
        "GLOBALTALK RESUME IDENTITY R7I.2",
    )
    for marker in required:
        if marker not in text:
            die("required baseline marker missing: {}".format(marker))

    text = insert_helpers(text)
    text = patch_retrieve(text)
    text = patch_recursive(text)
    text = patch_batch_driver(text)
    write_text(path, text)

    print("Applied LocalTalk endurance R7S: {}".format(path))
    print("  data recovery budget: 6 consecutive no-progress attempts per incident")
    print("  successful resumed data clears the incident budget")
    print("  persistent partial checkpoints: nonzero CNID + exact size required")
    print("  checkpoint durability: fdatasync before atomic state publish")
    print("  completed checkpoints replace fragile mtime-only reuse when available")
    print("  unrecovered recursive files are deferred; tree traversal continues")
    print("  deferred phase: fresh AFP connection per pass, maximum 5 passes")
    print("  deferred no-progress recovery: one in-process recovery per fresh pass")
    print("  final unresolved paths are listed and the transfer exits nonzero")
    print("  healthy AFP/ATP request sizes, 7-send profile and 50ms pacing unchanged")


if __name__ == "__main__":
    main()
