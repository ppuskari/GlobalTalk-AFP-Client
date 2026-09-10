#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Interactive GlobalTalk AFP browser/downloader.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import os
import re
import shutil
import subprocess
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LS = os.path.join(ROOT, "build-native-atp-r1", "gt-afp-ls")
PULL = os.path.join(ROOT, "scripts", "gt-pull-resilient.py")
RESET = os.path.join(ROOT, "scripts", "gt-afp-reset.sh")

LIST_RE = re.compile(
    r"^([d-][rwx-]{9})\s+([0-9]+)\s+"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"([0-9]{2}:[0-9]{2})\s+(.*)$")

PAGER_INPUT = b"\n" * 8192


def pause(msg="Press Enter to continue..."):
    try:
        input(msg)
    except EOFError:
        pass


def run_capture(argv, env=None):
    try:
        out = subprocess.check_output(
            argv, stderr=subprocess.STDOUT, env=env)
        return 0, out.decode("utf-8", "replace")
    except subprocess.CalledProcessError as exc:
        data = exc.output or b""
        return exc.returncode, data.decode("utf-8", "replace")
    except OSError as exc:
        return 127, str(exc)


def run_capture_paged(argv, env=None):
    """Capture gt-afp-ls while automatically advancing its pager."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env)
        out, unused = proc.communicate(PAGER_INPUT)
        del unused
        return proc.returncode, (out or b"").decode("utf-8", "replace")
    except OSError as exc:
        return 127, str(exc)


def choose(title, values, allow_manual=False):
    while True:
        print()
        print(title)
        print("=" * len(title))
        for idx, value in enumerate(values, 1):
            print("%3d. %s" % (idx, value))
        if allow_manual:
            print("  m. Enter manually")
        print("  q. Quit/back")
        try:
            answer = input("> ").strip()
        except EOFError:
            return None
        if answer.lower() == "q":
            return None
        if allow_manual and answer.lower() == "m":
            try:
                value = input("Name: ").strip()
            except EOFError:
                return None
            if value:
                return value
            continue
        try:
            pos = int(answer)
        except ValueError:
            continue
        if 1 <= pos <= len(values):
            return values[pos - 1]


def discover_zones():
    if shutil.which("getzones"):
        rc, text = run_capture(["getzones"])
        if rc == 0:
            zones = []
            for line in text.splitlines():
                value = line.strip()
                if value and value not in zones:
                    zones.append(value)
            if zones:
                return zones
    return []


def discover_servers(zone):
    query = "=:AFPServer@%s" % zone
    rc, text = run_capture(["nbplkup", query])
    if rc != 0:
        print(text)
        return []
    servers = []
    for line in text.splitlines():
        marker = ":AFPServer"
        if marker not in line:
            continue
        name = line.split(marker, 1)[0].strip()
        if name and name not in servers:
            servers.append(name)
    return servers


def make_url(server, zone, volume=None, parts=None):
    url = "afp+ddp://%s@%s" % (server, zone)
    if volume is not None:
        url += "/" + volume
    if parts:
        url += "/" + "/".join(parts)
    return url


def compat_env(enabled):
    env = os.environ.copy()
    if enabled:
        env["GT_AFP_DATE_COMPAT"] = "legacy1900"
    else:
        env.pop("GT_AFP_DATE_COMPAT", None)
    return env


def reset_daemon(env):
    if not os.path.exists(RESET):
        return
    subprocess.call([RESET], env=env)


def list_volumes(server, zone, env):
    rc, text = run_capture_paged([LS, make_url(server, zone)], env=env)
    if rc != 0:
        print(text)
        return []

    volumes = []
    in_volumes = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Available volumes on "):
            in_volumes = True
            continue
        if not in_volumes or not stripped:
            continue
        if stripped.startswith("Connected to server"):
            continue
        if stripped.startswith("Volume "):
            continue
        volumes.append(stripped)
    return volumes


def list_directory(server, zone, volume, parts, env):
    url = make_url(server, zone, volume, parts)
    rc, text = run_capture_paged([LS, url], env=env)
    if rc != 0:
        print(text)
        return None

    entries = []
    for line in text.splitlines():
        match = LIST_RE.match(line)
        if not match:
            continue
        mode, size, date, tm, name = match.groups()
        entries.append({
            "dir": mode.startswith("d"),
            "mode": mode,
            "size": int(size),
            "date": date,
            "time": tm,
            "name": name,
        })
    return entries


def default_download_root():
    preferred = "/home/pi/A2FILES"
    if os.path.isdir(preferred):
        return preferred
    return os.getcwd()


def download_node(server, zone, volume, parts, env):
    remote = make_url(server, zone, volume, parts)
    leaf = parts[-1] if parts else volume
    suggested = os.path.join(default_download_root(), leaf)

    print()
    print("Remote base:")
    print(remote)
    print()
    print("Local destination")
    print("Default: %s" % suggested)
    try:
        dest = input("> ").strip()
    except EOFError:
        return
    if not dest:
        dest = suggested
    dest = os.path.expanduser(dest)

    print()
    print("Download base:")
    print("  remote: %s" % remote)
    print("  local:  %s" % dest)
    print("  mode:   R5 checkpointed per-file recovery")
    try:
        answer = input("Start recursive download? [y/N] ").strip().lower()
    except EOFError:
        return
    if answer not in ("y", "yes"):
        return

    rc = subprocess.call([sys.executable, PULL, remote, dest], env=env)
    print()
    print("Downloader exit status: %d" % rc)
    pause()


def browse_volume(server, zone, volume, compat):
    parts = []
    env = compat_env(compat)

    while True:
        entries = list_directory(server, zone, volume, parts, env)
        if entries is None:
            pause()
            return compat

        print()
        print("GlobalTalk AFP Browser")
        print("======================")
        print("Zone:   %s" % zone)
        print("Server: %s" % server)
        print("Share:  %s" % volume)
        print("Path:   /%s" % "/".join(parts))
        print("Dates:  %s" % (
            "classic Finder compatibility" if compat else "AFP standard"))
        print("Pull:   R5 checkpointed recovery")
        print()

        for idx, entry in enumerate(entries, 1):
            kind = "DIR " if entry["dir"] else "FILE"
            print("%3d. %-4s %10d  %s %s  %s" % (
                idx, kind, entry["size"], entry["date"],
                entry["time"], entry["name"]))

        print()
        print("Commands:")
        print("  number   enter directory")
        print("  d        download current directory as base")
        print("  g N      download numbered file/directory as base")
        print("  u        go up")
        print("  c        toggle classic Finder date compatibility")
        print("  q        back to shares")

        try:
            answer = input("> ").strip()
        except EOFError:
            return compat

        if not answer:
            continue
        low = answer.lower()

        if low == "q":
            return compat
        if low == "u":
            if parts:
                parts.pop()
            else:
                return compat
            continue
        if low == "d":
            download_node(server, zone, volume, parts, env)
            continue
        if low == "c":
            compat = not compat
            env = compat_env(compat)
            print("Restarting afpsld so it inherits the new date mode...")
            reset_daemon(env)
            continue
        if low.startswith("g "):
            try:
                pos = int(answer.split(None, 1)[1])
            except (ValueError, IndexError):
                continue
            if 1 <= pos <= len(entries):
                target = entries[pos - 1]
                download_node(server, zone, volume,
                              parts + [target["name"]], env)
            continue

        try:
            pos = int(answer)
        except ValueError:
            continue
        if 1 <= pos <= len(entries):
            target = entries[pos - 1]
            if target["dir"]:
                parts.append(target["name"])
            else:
                print("That node is a file. Use 'g %d' to download it." % pos)
                pause()


def main():
    for path in (LS, PULL):
        if not os.path.exists(path):
            print("Required component not found: %s" % path, file=sys.stderr)
            print("Build first with: sh scripts/build-filedates-r5.sh",
                  file=sys.stderr)
            return 1

    if not shutil.which("nbplkup"):
        print("nbplkup was not found in PATH.", file=sys.stderr)
        return 1

    compat = os.environ.get("GT_AFP_DATE_COMPAT") in (
        "1", "legacy1900", "finder")

    while True:
        zones = discover_zones()
        zone = choose("AppleTalk Zones", zones, allow_manual=True)
        if zone is None:
            return 0

        while True:
            servers = discover_servers(zone)
            server = choose("AFP Servers in %s" % zone,
                            servers, allow_manual=True)
            if server is None:
                break

            while True:
                env = compat_env(compat)
                volumes = list_volumes(server, zone, env)
                volume = choose("Shares on %s" % server,
                                volumes, allow_manual=True)
                if volume is None:
                    break
                compat = browse_volume(server, zone, volume, compat)


if __name__ == "__main__":
    sys.exit(main())
