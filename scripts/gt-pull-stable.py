#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Stable R7 user-facing downloader.
#
# Keeps the proven AFP path unchanged and adds a lightweight local progress
# display.  Progress is measured from only the file currently being written
# and its Netatalk .AppleDouble sidecar; it does not issue extra AFP requests
# and does not recursively scan the destination filesystem.
#
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import argparse
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
RESET = os.path.join(ROOT, "scripts", "gt-afp-reset.sh")
LOGDIR = os.path.join(ROOT, "logs")
DEFAULT_DOWNLOAD_ROOT = "/mnt/AFPSERVER/128G2/AFPFILES2"

PROFILE_SENDS = "7"
PROFILE_PACING_MS = "50"

R7B_RE = re.compile(
    r"^R7B: reusing caller/enumeration metadata path=(.*) size=([0-9]+)$")

IMPORTANT_PREFIXES = (
    "R7I:", "R7I.1:", "R7I.2:", "R7J:", "R7L:", "R7M:",
    "Warning:", "ERROR:", "Error ", "gt-afp-pull:", "Transfer complete.")


def format_bytes(value):
    value = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB")
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return "%d %s" % (int(value), units[idx])
    return "%.2f %s" % (value, units[idx])


def format_rate(value):
    return "%s/s" % format_bytes(value)


def safe_size(path):
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
    except OSError:
        pass
    return 0


def remote_path_parts(url):
    # URLs used by this client are intentionally human-readable rather than
    # aggressively percent encoded.  Split after authority; first component
    # is the AFP volume and the rest is the selected rooted path.
    marker = "://"
    pos = url.find(marker)
    rest = url[pos + len(marker):] if pos >= 0 else url
    slash = rest.find("/")
    if slash < 0:
        return "", ""
    path = rest[slash + 1:]
    values = [unquote(value) for value in path.split("/") if value != ""]
    if not values:
        return "", ""
    volume = values[0]
    selected = "/".join(values[1:])
    return volume, selected


def default_destination(url):
    volume, selected = remote_path_parts(url)
    leaf = ""
    if selected:
        leaf = selected.rsplit("/", 1)[-1]
    elif volume:
        leaf = volume
    if not leaf:
        leaf = "GlobalTalk Download"
    base = os.environ.get("GT_AFP_DOWNLOAD_ROOT", DEFAULT_DOWNLOAD_ROOT)
    return os.path.join(os.path.expanduser(base), leaf)


def local_path_for_remote(remote_path, selected_root, dest, recursive):
    if not recursive:
        return dest

    remote = remote_path.lstrip("/")
    root = selected_root.strip("/")
    if root:
        if remote == root:
            relative = ""
        elif remote.startswith(root + "/"):
            relative = remote[len(root) + 1:]
        else:
            # Defensive fallback for an unexpected server presentation.
            relative = remote
    else:
        relative = remote

    if not relative:
        return dest
    return os.path.join(dest, *relative.split("/"))


def appledouble_path(local_path):
    parent = os.path.dirname(local_path)
    name = os.path.basename(local_path)
    return os.path.join(parent, ".AppleDouble", name)


def current_delta(state):
    if state is None:
        return 0, 0

    data_now = safe_size(state["local"])
    side_now = safe_size(state["sidecar"])

    # If an existing file was truncated after we sampled its old size, detect
    # that transition and start measuring the fresh copy from zero.
    if data_now < state["data_base"]:
        state["data_base"] = 0
    if side_now < state["side_base"]:
        state["side_base"] = 0

    data = max(0, data_now - state["data_base"])
    side = max(0, side_now - state["side_base"])
    return data, side


def finalize_current(state, committed):
    if state is None:
        return committed, 0
    data, side = current_delta(state)
    return committed + data + side, 1


def clear_status(tty):
    if tty:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def print_status(tty, text):
    if tty:
        sys.stdout.write("\r\033[K" + text)
        sys.stdout.flush()
    else:
        print(text)


def important_line(line):
    for prefix in IMPORTANT_PREFIXES:
        if line.startswith(prefix):
            return True
    return False


def reader_thread(proc, output_queue, logfile):
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


def ensure_logdir():
    if os.path.isdir(LOGDIR):
        return
    try:
        os.mkdir(LOGDIR)
    except OSError as exc:
        raise RuntimeError("could not create log directory %s: %s" %
                           (LOGDIR, exc))


def reset_daemon(env, quiet=False):
    if not os.path.exists(RESET):
        return
    if quiet:
        with open(os.devnull, "w") as devnull:
            subprocess.call([RESET], env=env, stdout=devnull, stderr=devnull)
    else:
        subprocess.call([RESET], env=env)


def build_parser():
    parser = argparse.ArgumentParser(
        description="GlobalTalk AFP Client Stable R7 downloader")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="recursively retrieve a selected directory")
    parser.add_argument("-d", "--dest", dest="dest",
                        help="local destination; default is source leaf under "
                             "/mnt/AFPSERVER/128G2/AFPFILES2")
    parser.add_argument("--verbose", action="store_true",
                        help="echo every raw gt-afp-pull line while copying")
    parser.add_argument("url", help="afp+ddp://OBJECT@ZONE/VOLUME/path")
    parser.add_argument("local_path", nargs="?",
                        help="optional local destination (same as --dest)")
    return parser


def main():
    args = build_parser().parse_args()

    if args.dest and args.local_path:
        print("Specify the destination once: --dest or LOCAL_PATH, not both.",
              file=sys.stderr)
        return 2

    if not os.path.isfile(PULL) or not os.access(PULL, os.X_OK):
        print("Stable downloader not found: %s" % PULL, file=sys.stderr)
        print("Build first with: sh scripts/build-stable-r7.sh",
              file=sys.stderr)
        return 1

    dest = args.dest or args.local_path or default_destination(args.url)
    dest = os.path.abspath(os.path.expanduser(dest))
    parent = os.path.dirname(dest.rstrip(os.sep)) or os.curdir
    if not os.path.isdir(parent):
        print("Destination parent does not exist: %s" % parent,
              file=sys.stderr)
        print("Stable pull does not create destination parent directories.",
              file=sys.stderr)
        return 1

    try:
        ensure_logdir()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["GT_AFP_R7K_ATP_SENDS"] = PROFILE_SENDS
    env["GT_AFP_R7K_INTERFILE_MS"] = PROFILE_PACING_MS
    env["GT_AFP_R7M_SKIP_POISON_CLOSE"] = "0"

    stamp = time.strftime("%Y%m%d-%H%M%S")
    logpath = os.path.join(LOGDIR, "stable-r7-pull-%s.log" % stamp)

    volume, selected_root = remote_path_parts(args.url)
    del volume

    print("GlobalTalk AFP Client Stable R7")
    print("  profile:     7 sends / 2 sec / 50 ms")
    print("  remote:      %s" % args.url)
    print("  local:       %s" % dest)
    print("  mode:        %s" % ("recursive" if args.recursive else "single node"))
    print("  progress:    data + .AppleDouble resource/metadata bytes (approx.)")
    print("  abort:       Ctrl-C")
    print("  log:         %s" % logpath)
    print()

    # A fresh afpsld is important because the daemon inherits ATP retry policy
    # from the environment only when it starts.
    reset_daemon(env, quiet=True)

    command = [PULL]
    if args.recursive:
        command.append("-r")
    command.extend(["-V", "-M", "netatalk", args.url, dest])
    if shutil.which("stdbuf"):
        command = ["stdbuf", "-oL", "-eL"] + command

    tty = sys.stdout.isatty()
    output_queue = queue.Queue()
    current = None
    committed = 0
    files_done = 0
    start = time.time()
    last_tick = start
    last_total = 0
    last_plain_print = start
    spinner_chars = "|/-\\"
    spinner_pos = 0
    aborted = False

    with open(logpath, "w") as logfile:
        logfile.write("Stable R7 profile: 7 sends / 2 sec / 50 ms\n")
        logfile.write("Remote: %s\n" % args.url)
        logfile.write("Local: %s\n\n" % dest)
        logfile.flush()

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env)

        thread = threading.Thread(
            target=reader_thread, args=(proc, output_queue, logfile))
        thread.daemon = True
        thread.start()

        reader_done = False
        try:
            while True:
                now = time.time()
                lines = []
                try:
                    item = output_queue.get(timeout=0.20)
                    lines.append(item)
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
                        committed, increment = finalize_current(
                            current, committed)
                        files_done += increment

                        remote_path = match.group(1)
                        expected = int(match.group(2))
                        local = local_path_for_remote(
                            remote_path, selected_root, dest, args.recursive)
                        sidecar = appledouble_path(local)
                        current = {
                            "remote": remote_path,
                            "name": os.path.basename(remote_path),
                            "local": local,
                            "sidecar": sidecar,
                            "expected": expected,
                            "data_base": safe_size(local),
                            "side_base": safe_size(sidecar),
                        }

                    if args.verbose or important_line(line):
                        clear_status(tty)
                        print(line)

                if now - last_tick >= 1.0:
                    data, side = current_delta(current)
                    total = committed + data + side
                    interval = max(0.001, now - last_tick)
                    instant = max(0.0, float(total - last_total) / interval)
                    elapsed = max(0.001, now - start)
                    average = float(total) / elapsed

                    if current is not None:
                        expected = current["expected"]
                        if expected > 0:
                            pct = min(100.0, 100.0 * float(data) / expected)
                            data_text = "data %.0f%%" % pct
                        else:
                            data_text = "data empty"
                        current_text = "%s | %s | sidecar %s" % (
                            current["name"], data_text, format_bytes(side))
                    else:
                        current_text = "starting session"

                    status = ("[%s] %s | preserved %s | now %s | avg %s | "
                              "files %d | %s | Ctrl-C abort" % (
                                  spinner_chars[spinner_pos % len(spinner_chars)],
                                  time.strftime("%H:%M:%S", time.gmtime(elapsed)),
                                  format_bytes(total), format_rate(instant),
                                  format_rate(average), files_done, current_text))
                    spinner_pos += 1

                    if tty:
                        print_status(True, status)
                    elif now - last_plain_print >= 5.0:
                        print_status(False, status)
                        last_plain_print = now

                    last_total = total
                    last_tick = now

                if reader_done and proc.poll() is not None:
                    break

        except KeyboardInterrupt:
            aborted = True
            clear_status(tty)
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

        committed, increment = finalize_current(current, committed)
        files_done += increment
        elapsed = max(0.001, time.time() - start)
        clear_status(tty)

        summary = ("Preserved approximately %s across %d files in %.1f sec "
                   "(aggregate avg %s)." % (
                       format_bytes(committed), files_done, elapsed,
                       format_rate(float(committed) / elapsed)))
        print(summary)
        print("Raw log: %s" % logpath)
        logfile.write("\n" + summary + "\n")

        if aborted:
            logfile.write("Transfer aborted by Ctrl-C.\n")
            reset_daemon(env, quiet=True)
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
