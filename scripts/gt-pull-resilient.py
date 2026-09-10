#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# GlobalTalk AFP resilient recursive pull R5.
#
# Deliberately does not change ATP/ASP transport.  It checkpoints at the
# remote-object boundary: enumerate a directory, transfer one file, and only
# then advance.  A failed list or file transfer gets one fresh-session retry;
# a persistently bad file is recorded and traversal continues.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import os
import re
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LS = os.path.join(ROOT, "build-native-atp-r1", "gt-afp-ls")
PULL = os.path.join(ROOT, "build-native-atp-r1", "gt-afp-pull")
RESET = os.path.join(ROOT, "scripts", "gt-afp-reset.sh")

LIST_RE = re.compile(
    r"^([d-][rwx-]{9})\s+([0-9]+)\s+"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"([0-9]{2}:[0-9]{2})\s+(.*)$")

MAX_FILE_ATTEMPTS = int(os.environ.get("GT_AFP_R5_FILE_ATTEMPTS", "2"))
MAX_LIST_ATTEMPTS = int(os.environ.get("GT_AFP_R5_LIST_ATTEMPTS", "2"))
ROTATE_EVERY = int(os.environ.get("GT_AFP_R5_ROTATE_EVERY", "0"))

# gt-afp-ls is historically interactive and pauses after a terminal-sized
# page (for example, "49 entries shown; press any key for next page").
# R5 is a batch consumer, so feed enough continuation keystrokes for even
# very large classic-Mac directories.  Excess bytes simply disappear when
# the child exits.  This does not alter AFP/ATP/ASP behavior.
PAGER_INPUT = b"\n" * 8192


def run(argv, env=None):
    try:
        return subprocess.call(argv, env=env)
    except OSError as exc:
        print("R5: cannot execute %s: %s" % (argv[0], exc), file=sys.stderr)
        return 127


def capture(argv, env=None):
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env)
        out, unused = proc.communicate(PAGER_INPUT)
        del unused
        text = (out or b"").decode("utf-8", "replace")
        return proc.returncode, text
    except OSError as exc:
        return 127, str(exc)


def reset_session(reason):
    print()
    print("R5: restarting AFP session: %s" % reason)
    if not os.path.exists(RESET):
        print("R5: reset helper missing: %s" % RESET, file=sys.stderr)
        return False
    rc = run([RESET])
    if rc != 0:
        print("R5: reset refused/failed; another AFP client may be active.",
              file=sys.stderr)
        return False
    time.sleep(1)
    return True


def parse_url(url):
    prefix = "afp+ddp://"
    if not url.startswith(prefix):
        raise ValueError("R5 currently requires an afp+ddp:// URL")
    rest = url[len(prefix):]
    slash = rest.find("/")
    if slash < 0:
        raise ValueError("R5 URL must include a volume")
    authority = rest[:slash]
    tail = rest[slash + 1:]
    parts = tail.split("/") if tail else []
    if not parts or not parts[0]:
        raise ValueError("R5 URL must include a volume")
    return prefix + authority, parts[0], parts[1:]


def make_url(authority, volume, parts):
    url = authority + "/" + volume
    if parts:
        url += "/" + "/".join(parts)
    return url


def list_dir(url):
    attempt = 1
    while attempt <= MAX_LIST_ATTEMPTS:
        rc, text = capture([LS, url])
        if rc == 0:
            entries = []
            for line in text.splitlines():
                match = LIST_RE.match(line)
                if not match:
                    continue
                mode, size, date, tm, name = match.groups()
                entries.append({
                    "dir": mode.startswith("d"),
                    "size": int(size),
                    "name": name,
                })
            return entries

        print(text)
        if attempt >= MAX_LIST_ATTEMPTS:
            return None
        if not reset_session("directory listing failed"):
            return None
        attempt += 1
    return None


def pull_file(url, local_dir):
    attempt = 1
    while attempt <= MAX_FILE_ATTEMPTS:
        print()
        print("R5: file attempt %d/%d" % (attempt, MAX_FILE_ATTEMPTS))
        print("R5: remote: %s" % url)
        print("R5: local:  %s" % local_dir)
        rc = run([PULL, "-V", "-M", "netatalk", url, local_dir])
        if rc == 0:
            return True

        if attempt >= MAX_FILE_ATTEMPTS:
            return False
        if not reset_session("file or metadata operation failed"):
            return False
        attempt += 1
    return False


def main():
    if len(sys.argv) != 3:
        print("Usage:", file=sys.stderr)
        print("  %s 'REMOTE_AFP_URL' LOCAL_DIRECTORY" % sys.argv[0],
              file=sys.stderr)
        return 2

    if MAX_FILE_ATTEMPTS < 1 or MAX_LIST_ATTEMPTS < 1 or ROTATE_EVERY < 0:
        print("R5 retry/rotate settings are invalid.", file=sys.stderr)
        return 2

    for path in (LS, PULL):
        if not os.path.exists(path):
            print("R5: required binary missing: %s" % path, file=sys.stderr)
            print("Build first with: sh scripts/build-filedates-r5.sh",
                  file=sys.stderr)
            return 1

    source = sys.argv[1]
    dest_root = os.path.abspath(os.path.expanduser(sys.argv[2]))

    try:
        authority, volume, base_parts = parse_url(source)
    except ValueError as exc:
        print("R5: %s" % exc, file=sys.stderr)
        return 2

    if not os.path.isdir(dest_root):
        os.makedirs(dest_root)

    failures = []
    completed = [0]

    # Stack entries are (remote path parts, local directory).
    stack = [(base_parts, dest_root)]

    print("R5 checkpointed recursive downloader")
    print("Remote base: %s" % source)
    print("Local base:  %s" % dest_root)
    print("File attempts: %d" % MAX_FILE_ATTEMPTS)
    print("List attempts: %d" % MAX_LIST_ATTEMPTS)
    print("Directory pagination: automatic")
    if ROTATE_EVERY:
        print("Proactive session rotation every %d completed files" % ROTATE_EVERY)

    while stack:
        remote_parts, local_dir = stack.pop()
        if not os.path.isdir(local_dir):
            os.makedirs(local_dir)

        directory_url = make_url(authority, volume, remote_parts)
        print()
        print("R5: listing %s" % directory_url)
        entries = list_dir(directory_url)
        if entries is None:
            print("R5: SKIP directory after recovery failure: %s" % directory_url,
                  file=sys.stderr)
            failures.append((directory_url, "list"))
            continue

        dirs = []
        files = []
        for entry in entries:
            if entry["dir"]:
                dirs.append(entry)
            else:
                files.append(entry)

        for entry in files:
            file_parts = remote_parts + [entry["name"]]
            file_url = make_url(authority, volume, file_parts)
            if pull_file(file_url, local_dir):
                completed[0] += 1
                print("R5: PASS object %d: %s" %
                      (completed[0], entry["name"]))
                if ROTATE_EVERY and completed[0] % ROTATE_EVERY == 0:
                    if not reset_session("proactive checkpoint rotation"):
                        print("R5: proactive rotation skipped.", file=sys.stderr)
            else:
                print("R5: SKIP file after %d attempts: %s" %
                      (MAX_FILE_ATTEMPTS, file_url), file=sys.stderr)
                failures.append((file_url, "file"))

        # Push in reverse so the server listing order is retained.
        for entry in reversed(dirs):
            child_parts = remote_parts + [entry["name"]]
            child_local = os.path.join(local_dir, entry["name"])
            stack.append((child_parts, child_local))

    print()
    print("R5 summary")
    print("==========")
    print("Completed files: %d" % completed[0])
    print("Failures:        %d" % len(failures))
    if failures:
        for url, kind in failures:
            print("  %s: %s" % (kind, url))
        return 1

    print("Recursive download complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
