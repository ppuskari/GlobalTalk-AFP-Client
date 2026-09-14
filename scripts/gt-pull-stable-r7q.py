#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Stable R7 UI: R7P authoritative payload + R7Q retry-safe reuse.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import argparse
import collections
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
try:
    from urllib.parse import unquote
except ImportError:
    from urllib import unquote

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PULL = os.path.join(ROOT, "build-stable-r7", "gt-afp-pull")
LS = os.path.join(ROOT, "build-stable-r7", "gt-afp-ls")
RESET = os.path.join(ROOT, "scripts", "gt-afp-reset.sh")
LOGDIR = os.path.join(ROOT, "logs")
DEFAULT_ROOT = "/mnt/AFPSERVER/128G2/AFPFILES2"
PAGER_INPUT = b"\n" * 8192

R7B_RE = re.compile(
    r"^R7B: reusing caller/enumeration metadata path=(.*) size=([0-9]+)$")
R7P_RE = re.compile(
    r"^R7P: (data|resource) path=(.*) delta=([0-9]+) "
    r"total=([0-9]+) expected=([0-9]+)$")
R7Q_SKIP_RE = re.compile(
    r"^R7Q: skip-data size=([0-9]+) path=(.*)$")
LIST_RE = re.compile(
    r"^([d-][rwx-]{9})\s+([0-9]+)\s+"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"([0-9]{2}:[0-9]{2})\s+(.*)$")

IMPORTANT = (
    "R7I:", "R7I.1:", "R7I.2:", "R7J:", "R7L:", "R7M:",
    "Warning:", "ERROR:", "Error ", "gt-afp-pull:", "Transfer complete.")


def fmt_bytes(value):
    value = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB")
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return "%d %s" % (int(value), units[idx])
    return "%.2f %s" % (value, units[idx])


def fmt_rate(value):
    return fmt_bytes(value) + "/s"


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return "%dh%02dm" % (hours, minutes)
    if minutes:
        return "%dm%02ds" % (minutes, secs)
    return "%ds" % secs


def split_url(url):
    marker = "://"
    pos = url.find(marker)
    start = pos + len(marker) if pos >= 0 else 0
    slash = url.find("/", start)
    if slash < 0:
        return url, []
    authority = url[:slash]
    parts = [unquote(x) for x in url[slash + 1:].split("/") if x]
    return authority, parts


def join_url(authority, parts):
    if not parts:
        return authority
    return authority + "/" + "/".join(parts)


def default_dest(url):
    unused, parts = split_url(url)
    del unused
    leaf = parts[-1] if parts else "GlobalTalk Download"
    root = os.environ.get("GT_AFP_DOWNLOAD_ROOT", DEFAULT_ROOT)
    return os.path.join(os.path.expanduser(root), leaf)


def ensure_logdir():
    if not os.path.isdir(LOGDIR):
        os.mkdir(LOGDIR)


def reset_daemon(env):
    if not os.path.exists(RESET):
        return
    with open(os.devnull, "w") as null:
        subprocess.call([RESET], env=env, stdout=null, stderr=null)


def run_ls(url, env):
    try:
        proc = subprocess.Popen(
            [LS, url], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=env)
        output, unused = proc.communicate(PAGER_INPUT)
        del unused
        return proc.returncode, (output or b"").decode("utf-8", "replace")
    except OSError as exc:
        return 127, str(exc)


def parse_listing(text):
    result = []
    for line in text.splitlines():
        match = LIST_RE.match(line)
        if not match:
            continue
        mode, size, date, tm, name = match.groups()
        del date, tm
        result.append({
            "dir": mode.startswith("d"),
            "size": int(size),
            "name": name,
        })
    return result


def preflight(url, env):
    authority, root = split_url(url)
    if not root:
        return None, "URL does not identify a volume/directory"

    stack = [list(root)]
    files = 0
    dirs = 0
    data = 0

    while stack:
        parts = stack.pop()
        child_url = join_url(authority, parts)
        rc, text = run_ls(child_url, env)
        if rc:
            return None, "listing failed at %s (rc=%d)" % (child_url, rc)

        dirs += 1
        for item in parse_listing(text):
            if item["dir"]:
                stack.append(parts + [item["name"]])
            else:
                files += 1
                data += item["size"]

        sys.stdout.write(
            "\rCatalog: %d dirs | %d files | %s data forks" %
            (dirs, files, fmt_bytes(data)))
        sys.stdout.flush()

    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    return {"files": files, "dirs": dirs, "data": data}, None


def reader(proc, output_queue, logfile):
    try:
        while True:
            line = proc.stdout.readline()
            if line == "":
                break
            logfile.write(line)
            logfile.flush()
            output_queue.put(line.rstrip("\n"))
    finally:
        output_queue.put(None)


def important(line):
    return any(line.startswith(prefix) for prefix in IMPORTANT)


def clear_live(tty):
    if tty:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def progress_fraction(done_files, total_files, logical_data, total_data):
    values = []
    if total_files:
        values.append(min(1.0, float(done_files) / float(total_files)))
    if total_data:
        values.append(min(1.0, float(logical_data) / float(total_data)))
    if not values:
        return 0.0
    return min(values)


def new_current(path, expected_data=0, skipped=False):
    return {
        "path": path,
        "name": os.path.basename(path),
        "expected_data": int(expected_data),
        "data": 0,
        "logical_data": int(expected_data) if skipped else 0,
        "resource": 0,
        "expected_resource": 0,
        "skipped": bool(skipped),
    }


def finalize(current, totals):
    if current is None:
        return
    totals["payload_data"] += current["data"]
    totals["logical_data"] += max(current["logical_data"], current["data"])
    totals["resource"] += current["resource"]
    totals["files"] += 1
    if current["skipped"]:
        totals["reused_files"] += 1
        totals["reused_bytes"] += current["expected_data"]


def build_parser():
    parser = argparse.ArgumentParser(
        description="GlobalTalk AFP Stable R7Q retry-safe pull")
    parser.add_argument("-r", "--recursive", action="store_true")
    parser.add_argument("-d", "--dest")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    parser.add_argument("url")
    parser.add_argument("local_path", nargs="?")
    return parser


def main():
    args = build_parser().parse_args()

    if args.dest and args.local_path:
        print("Specify destination once: --dest or LOCAL_PATH.",
              file=sys.stderr)
        return 2

    for binary in (PULL, LS):
        if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            print("Missing stable component: %s" % binary, file=sys.stderr)
            print("Run: sh scripts/build-stable-r7q-ui.sh", file=sys.stderr)
            return 1

    dest = os.path.abspath(os.path.expanduser(
        args.dest or args.local_path or default_dest(args.url)))
    parent = os.path.dirname(dest.rstrip(os.sep)) or os.curdir
    if not os.path.isdir(parent):
        print("Destination parent does not exist: %s" % parent,
              file=sys.stderr)
        return 1

    ensure_logdir()
    env = os.environ.copy()
    env["GT_AFP_R7K_ATP_SENDS"] = "7"
    env["GT_AFP_R7K_INTERFILE_MS"] = "50"
    env["GT_AFP_R7M_SKIP_POISON_CLOSE"] = "0"
    env["GT_AFP_PROGRESS_TELEMETRY"] = "1"

    stamp = time.strftime("%Y%m%d-%H%M%S")
    logpath = os.path.join(LOGDIR, "stable-r7q-pull-%s.log" % stamp)

    print("GlobalTalk AFP Client Stable R7Q")
    print("  profile:   7 sends / 2 sec / 50 ms")
    print("  remote:    %s" % args.url)
    print("  local:     %s" % dest)
    print("  retry:     same size+mtime reuses data; metadata is refreshed")
    print("  meter:     actual AFP payload + logical whole-tree completion")
    print("  abort:     Ctrl-C")
    print("  log:       %s" % logpath)
    print()

    reset_daemon(env)
    catalog = None
    if args.recursive and not args.no_preflight:
        print("Scanning selected tree for whole-copy progress...")
        catalog, error = preflight(args.url, env)
        if catalog:
            print("Catalog: %d files in %d dirs; %s known data forks." %
                  (catalog["files"], catalog["dirs"],
                   fmt_bytes(catalog["data"])))
            print("Resource-fork bytes are learned live; ETA is approximate.")
        else:
            print("Catalog unavailable: %s" % error)
            print("Continuing with live-only progress.")
        print()
        reset_daemon(env)

    command = [PULL]
    if args.recursive:
        command.append("-r")
    command.extend(["-V", "-M", "netatalk", args.url, dest])
    if shutil.which("stdbuf"):
        command = ["stdbuf", "-oL", "-eL"] + command

    total_files = catalog["files"] if catalog else 0
    total_data = catalog["data"] if catalog else 0
    totals = {
        "payload_data": 0,
        "logical_data": 0,
        "resource": 0,
        "files": 0,
        "reused_files": 0,
        "reused_bytes": 0,
    }
    current = None
    output_queue = queue.Queue()
    tty = sys.stdout.isatty()
    start = time.time()
    last_status = start
    last_history = start
    rate_history = collections.deque()
    aborted = False
    reader_done = False

    with open(logpath, "w") as logfile:
        logfile.write("Stable R7Q retry-safe pull\n")
        logfile.write("Remote: %s\nLocal: %s\n\n" % (args.url, dest))
        logfile.flush()

        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, bufsize=1, env=env)
        thread = threading.Thread(
            target=reader, args=(proc, output_queue, logfile))
        thread.daemon = True
        thread.start()

        try:
            while True:
                now = time.time()
                lines = []
                try:
                    lines.append(output_queue.get(timeout=0.20))
                    while True:
                        try:
                            lines.append(output_queue.get_nowait())
                        except queue.Empty:
                            break
                except queue.Empty:
                    pass

                for line in lines:
                    if line is None:
                        reader_done = True
                        continue

                    match = R7B_RE.match(line)
                    if match:
                        finalize(current, totals)
                        current = new_current(
                            match.group(1), int(match.group(2)), False)

                    skip = R7Q_SKIP_RE.match(line)
                    if skip:
                        skip_size = int(skip.group(1))
                        skip_path = skip.group(2)
                        if current is None or current["path"] != skip_path:
                            finalize(current, totals)
                            current = new_current(skip_path, skip_size, True)
                        else:
                            current["expected_data"] = max(
                                current["expected_data"], skip_size)
                            current["logical_data"] = skip_size
                            current["skipped"] = True

                    progress = R7P_RE.match(line)
                    if progress:
                        kind, path, delta, total, expected = progress.groups()
                        del delta
                        total = int(total)
                        expected = int(expected)
                        if current is None or current["path"] != path:
                            finalize(current, totals)
                            current = new_current(path, 0, False)

                        if kind == "data":
                            current["data"] = max(current["data"], total)
                            current["logical_data"] = max(
                                current["logical_data"], total)
                            current["expected_data"] = max(
                                current["expected_data"], expected)
                        else:
                            current["resource"] = max(
                                current["resource"], total)
                            current["expected_resource"] = max(
                                current["expected_resource"], expected)

                    if args.verbose or important(line):
                        clear_live(tty)
                        print(line)

                if now - last_status >= 1.0:
                    cur_data = current["data"] if current else 0
                    cur_logical = current["logical_data"] if current else 0
                    cur_resource = current["resource"] if current else 0
                    payload = (totals["payload_data"] + cur_data +
                               totals["resource"] + cur_resource)
                    logical_data = (totals["logical_data"] +
                                    max(cur_logical, cur_data))
                    done_files = totals["files"]
                    reused_files = totals["reused_files"]
                    if current and current["skipped"]:
                        reused_preview = reused_files + 1
                    else:
                        reused_preview = reused_files

                    elapsed = max(0.001, now - start)
                    rate_history.append((now, payload))
                    while rate_history and now - rate_history[0][0] > 8.0:
                        rate_history.popleft()
                    if len(rate_history) >= 2:
                        span = max(0.001,
                                   rate_history[-1][0] - rate_history[0][0])
                        live_rate = float(
                            rate_history[-1][1] - rate_history[0][1]) / span
                    else:
                        live_rate = 0.0
                    avg_rate = float(payload) / elapsed

                    if catalog:
                        file_pct = (100.0 * done_files / total_files
                                    if total_files else 100.0)
                        data_pct = (min(100.0,
                                        100.0 * logical_data / total_data)
                                    if total_data else 100.0)
                        fraction = progress_fraction(
                            done_files, total_files, logical_data, total_data)
                        if 0.005 < fraction < 1.0:
                            eta = elapsed * (1.0 - fraction) / fraction
                            eta_text = "ETA~%s" % fmt_time(eta)
                        elif fraction >= 1.0:
                            eta_text = "ETA~done"
                        else:
                            eta_text = "ETA~learning"
                        whole = ("files %d/%d %.1f%% | data %s/%s %.1f%% | "
                                 "reused %d | %s" %
                                 (done_files, total_files, file_pct,
                                  fmt_bytes(logical_data), fmt_bytes(total_data),
                                  data_pct, reused_preview, eta_text))
                    else:
                        whole = "files %d done | reused %d" % (
                            done_files, reused_preview)

                    if current:
                        if current["skipped"]:
                            data_text = "data reused"
                        elif current["expected_data"]:
                            pct = min(100.0,
                                      100.0 * current["data"] /
                                      current["expected_data"])
                            data_text = "data %.1f%%" % pct
                        else:
                            data_text = "data empty"

                        if current["expected_resource"]:
                            pct = min(100.0,
                                      100.0 * current["resource"] /
                                      current["expected_resource"])
                            resource_text = "rsrc %.1f%%" % pct
                        elif current["resource"]:
                            resource_text = "rsrc %s" % fmt_bytes(
                                current["resource"])
                        else:
                            resource_text = "rsrc --"

                        current_text = "%s | %s | %s" % (
                            current["name"], data_text, resource_text)
                    else:
                        current_text = "starting session"

                    status = ("%s | %s | payload %s | now %s | avg %s | %s | "
                              "Ctrl-C abort" %
                              (fmt_time(elapsed), whole, fmt_bytes(payload),
                               fmt_rate(live_rate), fmt_rate(avg_rate),
                               current_text))

                    if tty:
                        sys.stdout.write("\r\033[K" + status)
                        sys.stdout.flush()
                    elif now - last_history >= 5.0:
                        print(status)
                        last_history = now

                    if tty and now - last_history >= 10.0:
                        clear_live(True)
                        print(status)
                        last_history = now

                    last_status = now

                if reader_done and proc.poll() is not None:
                    break

        except KeyboardInterrupt:
            aborted = True
            clear_live(tty)
            print("Ctrl-C received; stopping transfer...")
            try:
                proc.send_signal(signal.SIGINT)
            except OSError:
                pass
            try:
                proc.wait()
            except Exception:
                try:
                    proc.terminate()
                except OSError:
                    pass
        finally:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait()
                except OSError:
                    pass

        finalize(current, totals)
        clear_live(tty)
        elapsed = max(0.001, time.time() - start)
        payload = totals["payload_data"] + totals["resource"]

        print("Transferred %s actual AFP payload in %.1f sec (avg %s)." %
              (fmt_bytes(payload), elapsed,
               fmt_rate(float(payload) / elapsed)))
        if totals["reused_files"]:
            print("Reused %d completed data forks (%s logical data)." %
                  (totals["reused_files"],
                   fmt_bytes(totals["reused_bytes"])))
        if catalog:
            print("Logical completion: files %d/%d; data %s/%s." %
                  (totals["files"], total_files,
                   fmt_bytes(totals["logical_data"]), fmt_bytes(total_data)))
        print("Raw log: %s" % logpath)

        if aborted:
            logfile.write("Transfer aborted by Ctrl-C.\n")
            reset_daemon(env)
            print("Transfer aborted; afpsld reset for the next selection.")
            return 130

        rc = proc.returncode
        logfile.write("gt-afp-pull exit code: %d\n" % rc)
        if rc == 0:
            print("Transfer complete.")
        else:
            print("Transfer failed with exit code %d." % rc)
        return rc


if __name__ == "__main__":
    sys.exit(main())
