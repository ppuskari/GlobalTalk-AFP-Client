#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Stable R7 UI with whole-tree preflight and authoritative R7P byte telemetry.
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
    i = 0
    while value >= 1024.0 and i < len(units) - 1:
        value /= 1024.0
        i += 1
    return ("%d %s" if i == 0 else "%.2f %s") % (value if i else int(value), units[i])


def fmt_rate(value):
    return fmt_bytes(value) + "/s"


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return "%dh%02dm" % (h, m)
    if m:
        return "%dm%02ds" % (m, s)
    return "%ds" % s


def split_url(url):
    marker = "://"
    p = url.find(marker)
    start = p + len(marker) if p >= 0 else 0
    slash = url.find("/", start)
    if slash < 0:
        return url, []
    authority = url[:slash]
    parts = [unquote(x) for x in url[slash + 1:].split("/") if x]
    return authority, parts


def default_dest(url):
    unused, parts = split_url(url)
    del unused
    leaf = parts[-1] if parts else "GlobalTalk Download"
    root = os.environ.get("GT_AFP_DOWNLOAD_ROOT", DEFAULT_ROOT)
    return os.path.join(os.path.expanduser(root), leaf)


def join_url(authority, parts):
    return authority if not parts else authority + "/" + "/".join(parts)


def reset_daemon(env):
    if not os.path.exists(RESET):
        return
    with open(os.devnull, "w") as null:
        subprocess.call([RESET], env=env, stdout=null, stderr=null)


def ensure_logdir():
    if not os.path.isdir(LOGDIR):
        os.mkdir(LOGDIR)


def run_ls(url, env):
    try:
        p = subprocess.Popen([LS, url], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=env)
        out, unused = p.communicate(PAGER_INPUT)
        del unused
        return p.returncode, (out or b"").decode("utf-8", "replace")
    except OSError as exc:
        return 127, str(exc)


def parse_listing(text):
    result = []
    for line in text.splitlines():
        m = LIST_RE.match(line)
        if not m:
            continue
        mode, size, date, tm, name = m.groups()
        del date, tm
        result.append({"dir": mode.startswith("d"),
                       "size": int(size), "name": name})
    return result


def preflight(url, env):
    authority, root = split_url(url)
    if not root:
        return None, "URL does not identify a volume/directory"
    stack = [list(root)]
    files = dirs = data = 0
    while stack:
        parts = stack.pop()
        rc, text = run_ls(join_url(authority, parts), env)
        if rc:
            return None, "listing failed at %s (rc=%d)" % (
                join_url(authority, parts), rc)
        dirs += 1
        for item in parse_listing(text):
            if item["dir"]:
                stack.append(parts + [item["name"]])
            else:
                files += 1
                data += item["size"]
        sys.stdout.write("\rCatalog: %d dirs | %d files | %s data forks" %
                         (dirs, files, fmt_bytes(data)))
        sys.stdout.flush()
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    return {"files": files, "dirs": dirs, "data": data}, None


def reader(proc, q, log):
    try:
        while True:
            line = proc.stdout.readline()
            if line == "":
                break
            log.write(line)
            log.flush()
            q.put(line.rstrip("\n"))
    finally:
        q.put(None)


def important(line):
    return any(line.startswith(x) for x in IMPORTANT)


def clear_live(tty):
    if tty:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def progress_fraction(done_files, total_files, data_done, total_data):
    values = []
    if total_files:
        values.append(min(1.0, float(done_files) / total_files))
    if total_data:
        values.append(min(1.0, float(data_done) / total_data))
    return min(values) if values else 0.0


def build_parser():
    p = argparse.ArgumentParser(description="GlobalTalk AFP Stable R7 pull")
    p.add_argument("-r", "--recursive", action="store_true")
    p.add_argument("-d", "--dest")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--no-preflight", action="store_true")
    p.add_argument("url")
    p.add_argument("local_path", nargs="?")
    return p


def main():
    args = build_parser().parse_args()
    if args.dest and args.local_path:
        print("Specify destination once: --dest or LOCAL_PATH.", file=sys.stderr)
        return 2
    for binary in (PULL, LS):
        if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            print("Missing stable component: %s" % binary, file=sys.stderr)
            print("Run: sh scripts/build-stable-r7.sh", file=sys.stderr)
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
    logpath = os.path.join(LOGDIR, "stable-r7-pull-%s.log" % stamp)

    print("GlobalTalk AFP Client Stable R7")
    print("  profile:   7 sends / 2 sec / 50 ms")
    print("  remote:    %s" % args.url)
    print("  local:     %s" % dest)
    print("  meter:     actual AFP data + resource payload bytes")
    print("  abort:     Ctrl-C")
    print("  log:       %s" % logpath)
    print()

    reset_daemon(env)
    catalog = None
    if args.recursive and not args.no_preflight:
        print("Scanning selected tree for whole-copy progress...")
        catalog, err = preflight(args.url, env)
        if catalog:
            print("Catalog: %d files in %d dirs; %s known data forks." %
                  (catalog["files"], catalog["dirs"],
                   fmt_bytes(catalog["data"])))
            print("Resource-fork bytes are learned live; ETA remains approximate.")
        else:
            print("Catalog unavailable: %s" % err)
            print("Continuing with live-only progress.")
        print()
        reset_daemon(env)

    cmd = [PULL]
    if args.recursive:
        cmd.append("-r")
    cmd.extend(["-V", "-M", "netatalk", args.url, dest])
    if shutil.which("stdbuf"):
        cmd = ["stdbuf", "-oL", "-eL"] + cmd

    total_files = catalog["files"] if catalog else 0
    total_data = catalog["data"] if catalog else 0
    q = queue.Queue()
    tty = sys.stdout.isatty()
    current = None
    committed_data = 0
    committed_resource = 0
    files_done = 0
    start = time.time()
    last_status = start
    last_history = start
    history = collections.deque()
    aborted = False
    reader_done = False

    with open(logpath, "w") as log:
        log.write("Stable R7 + R7P authoritative progress\n")
        log.write("Remote: %s\nLocal: %s\n\n" % (args.url, dest))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1, env=env)
        t = threading.Thread(target=reader, args=(proc, q, log))
        t.daemon = True
        t.start()

        try:
            while True:
                now = time.time()
                lines = []
                try:
                    lines.append(q.get(timeout=0.20))
                    while True:
                        try:
                            lines.append(q.get_nowait())
                        except queue.Empty:
                            break
                except queue.Empty:
                    pass

                for line in lines:
                    if line is None:
                        reader_done = True
                        continue

                    m = R7B_RE.match(line)
                    if m:
                        if current is not None:
                            committed_data += current["data"]
                            committed_resource += current["resource"]
                            files_done += 1
                        current = {"path": m.group(1),
                                   "name": os.path.basename(m.group(1)),
                                   "expected_data": int(m.group(2)),
                                   "data": 0,
                                   "resource": 0,
                                   "expected_resource": 0}

                    p = R7P_RE.match(line)
                    if p:
                        kind, path, delta, total, expected = p.groups()
                        del delta
                        total = int(total)
                        expected = int(expected)
                        if current is None or current["path"] != path:
                            # Defensive: telemetry should normally follow R7B.
                            if current is not None:
                                committed_data += current["data"]
                                committed_resource += current["resource"]
                                files_done += 1
                            current = {"path": path,
                                       "name": os.path.basename(path),
                                       "expected_data": 0,
                                       "data": 0,
                                       "resource": 0,
                                       "expected_resource": 0}
                        if kind == "data":
                            current["data"] = max(current["data"], total)
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
                    cur_res = current["resource"] if current else 0
                    data_done = committed_data + cur_data
                    resource_done = committed_resource + cur_res
                    payload = data_done + resource_done
                    elapsed = max(0.001, now - start)

                    history.append((now, payload))
                    while history and now - history[0][0] > 8.0:
                        history.popleft()
                    if len(history) >= 2:
                        dt = max(0.001, history[-1][0] - history[0][0])
                        live_rate = float(history[-1][1] - history[0][1]) / dt
                    else:
                        live_rate = 0.0
                    avg_rate = float(payload) / elapsed

                    if catalog:
                        fpct = (100.0 * files_done / total_files
                                if total_files else 100.0)
                        dpct = (min(100.0, 100.0 * data_done / total_data)
                                if total_data else 100.0)
                        fraction = progress_fraction(
                            files_done, total_files, data_done, total_data)
                        if 0.005 < fraction < 1.0:
                            eta = elapsed * (1.0 - fraction) / fraction
                            eta_text = "ETA~%s" % fmt_time(eta)
                        elif fraction >= 1.0:
                            eta_text = "ETA~done"
                        else:
                            eta_text = "ETA~learning"
                        whole = ("files %d/%d %.1f%% | data %s/%s %.1f%% | %s" %
                                 (files_done, total_files, fpct,
                                  fmt_bytes(data_done), fmt_bytes(total_data),
                                  dpct, eta_text))
                    else:
                        whole = "files %d done" % files_done

                    if current:
                        if current["expected_data"]:
                            cpct = min(100.0, 100.0 * current["data"] /
                                       current["expected_data"])
                            dtext = "data %.1f%%" % cpct
                        else:
                            dtext = "data empty"
                        if current["expected_resource"]:
                            rpct = min(100.0, 100.0 * current["resource"] /
                                       current["expected_resource"])
                            rtext = "rsrc %.1f%%" % rpct
                        elif current["resource"]:
                            rtext = "rsrc %s" % fmt_bytes(current["resource"])
                        else:
                            rtext = "rsrc --"
                        curtext = "%s | %s | %s" % (
                            current["name"], dtext, rtext)
                    else:
                        curtext = "starting session"

                    status = ("%s | %s | payload %s | now %s | avg %s | %s | "
                              "Ctrl-C abort" %
                              (fmt_time(elapsed), whole, fmt_bytes(payload),
                               fmt_rate(live_rate), fmt_rate(avg_rate), curtext))

                    if tty:
                        sys.stdout.write("\r\033[K" + status)
                        sys.stdout.flush()
                        if now - last_history >= 10.0:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            last_history = now
                    elif now - last_history >= 5.0:
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

        if current is not None:
            committed_data += current["data"]
            committed_resource += current["resource"]
            files_done += 1
        payload = committed_data + committed_resource
        elapsed = max(0.001, time.time() - start)
        clear_live(tty)
        print("Transferred %s AFP payload across %d files in %.1f sec "
              "(avg %s)." %
              (fmt_bytes(payload), files_done, elapsed,
               fmt_rate(float(payload) / elapsed)))
        if catalog:
            print("Catalog completion: files %d/%d; data %s/%s." %
                  (files_done, total_files, fmt_bytes(committed_data),
                   fmt_bytes(total_data)))
        print("Raw log: %s" % logpath)

        if aborted:
            reset_daemon(env)
            print("Transfer aborted; afpsld reset.")
            return 130
        if proc.returncode == 0:
            print("Transfer complete.")
        else:
            print("Transfer failed with exit code %d." % proc.returncode)
        return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
