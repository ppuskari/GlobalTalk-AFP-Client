#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# PuTTY-friendly Stable R7Q UI shim.
#
# Execute the tested R7Q implementation after applying presentation/launcher
# compatibility transforms in memory:
#   1. remove the deliberate 10-second permanent history line;
#   2. clamp live TTY status to the current terminal width;
#   3. pass AFP URLs/path arguments to POSIX child processes as explicit
#      UTF-8 bytes so Python 3.4 running in an ASCII locale cannot reject
#      classic Mac names such as the florin character (U+0192);
#   4. read gt-afp-pull stdout as raw bytes and decode explicitly as UTF-8
#      with replacement, preventing ASCII-locale UnicodeDecodeError crashes;
#   5. on a catalog directory-list failure, reset local AFP state and retry
#      that same directory once before falling back to live-only progress;
#   6. force terminal stdout/stderr and the per-run text log to UTF-8 so
#      filenames in diagnostics cannot raise UnicodeEncodeError.
#
# No AFP request, retry, recovery, metadata, or filesystem semantics change.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMPL = os.path.join(ROOT, "scripts", "gt-pull-stable-r7q.py")


def normalize_cli_text(value):
    """Recover UTF-8 argv text that Python 3.4 decoded with surrogateescape."""
    if value is None or isinstance(value, bytes):
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value
    try:
        raw = os.fsencode(value)
    except (UnicodeEncodeError, AttributeError):
        return value
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return value


def utf8_argv(argv):
    """Return POSIX argv as bytes, explicitly UTF-8 encoded."""
    result = []
    for item in argv:
        if isinstance(item, bytes):
            result.append(item)
        elif isinstance(item, str):
            result.append(normalize_cli_text(item).encode("utf-8"))
        else:
            result.append(item)
    return result


def force_utf8_stream(stream):
    """Rewrap a Python 3.4 stdio text stream as UTF-8 without closing fd."""
    try:
        if str(getattr(stream, "encoding", "")).lower().replace("-", "") == "utf8":
            return stream
        raw = stream.detach()
        return io.TextIOWrapper(
            raw, encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, io.UnsupportedOperation, ValueError):
        return stream


# Jessie may start Python with LANG/LC_ALL effectively ASCII.  Make our own
# operator-facing output byte-clean before the transformed implementation can
# print a classic Mac filename such as ƒ or any other non-ASCII character.
sys.stdout = force_utf8_stream(sys.stdout)
sys.stderr = force_utf8_stream(sys.stderr)

if not os.path.isfile(IMPL):
    print("Stable R7Q implementation missing: %s" % IMPL, file=sys.stderr)
    sys.exit(1)

# Do not let Jessie/Python 3.4 decode our own UTF-8 source using an ASCII
# process locale.  The implementation may itself contain classic-Mac Unicode
# examples and diagnostics.
with io.open(IMPL, "r", encoding="utf-8") as handle:
    source = handle.read()

history_block = '''                    if tty and now - last_history >= 10.0:\n                        clear_live(True)\n                        print(status)\n                        last_history = now\n\n'''
if history_block not in source:
    print("R7Q PuTTY shim: expected history block not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(history_block, "", 1)

write_block = '''                    if tty:\n                        sys.stdout.write("\\r\\033[K" + status)\n                        sys.stdout.flush()\n                    elif now - last_history >= 5.0:\n'''
write_replacement = '''                    if tty:\n                        try:\n                            columns = shutil.get_terminal_size((160, 24)).columns\n                        except Exception:\n                            columns = 160\n                        if columns > 8 and len(status) >= columns:\n                            status = status[:columns - 2] + ">"\n                        sys.stdout.write("\\r\\033[K" + status)\n                        sys.stdout.flush()\n                    elif now - last_history >= 5.0:\n'''
if write_block not in source:
    print("R7Q PuTTY shim: expected live-write block not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(write_block, write_replacement, 1)

parse_block = '''    args = build_parser().parse_args()\n\n'''
parse_replacement = '''    args = build_parser().parse_args()\n    args.url = normalize_cli_text(args.url)\n    args.dest = normalize_cli_text(args.dest) if args.dest is not None else None\n    args.local_path = (normalize_cli_text(args.local_path)\n                       if args.local_path is not None else None)\n\n'''
if parse_block not in source:
    print("R7Q PuTTY shim: parser guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(parse_block, parse_replacement, 1)

ls_block = '''        proc = subprocess.Popen(\n            [LS, url], stdin=subprocess.PIPE, stdout=subprocess.PIPE,\n'''
ls_replacement = '''        proc = subprocess.Popen(\n            utf8_argv([LS, url]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,\n'''
if ls_block not in source:
    print("R7Q PuTTY shim: catalog subprocess guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(ls_block, ls_replacement, 1)

preflight_block = '''        rc, text = run_ls(child_url, env)\n        if rc:\n            return None, "listing failed at %s (rc=%d)" % (child_url, rc)\n\n        dirs += 1\n'''
preflight_replacement = '''        rc, text = run_ls(child_url, env)\n        if rc:\n            first_rc = rc\n            first_text = text\n            reset_daemon(env)\n            time.sleep(1.0)\n            rc, text = run_ls(child_url, env)\n            if rc:\n                detail = (text.strip() or first_text.strip()).replace("\\n", " | ")\n                if len(detail) > 240:\n                    detail = detail[-240:]\n                suffix = (": " + detail) if detail else ""\n                return None, ("listing failed at %s "\n                              "(rc=%d; retry rc=%d)%s" %\n                              (child_url, first_rc, rc, suffix))\n\n        dirs += 1\n'''
if preflight_block not in source:
    print("R7Q PuTTY shim: catalog retry guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(preflight_block, preflight_replacement, 1)

pull_block = '''        proc = subprocess.Popen(\n            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n'''
pull_replacement = '''        proc = subprocess.Popen(\n            utf8_argv(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n'''
if pull_block not in source:
    print("R7Q PuTTY shim: pull subprocess guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(pull_block, pull_replacement, 1)

text_mode_block = '''            universal_newlines=True, bufsize=1, env=env)\n'''
text_mode_replacement = '''            bufsize=0, env=env)\n'''
if text_mode_block not in source:
    print("R7Q PuTTY shim: subprocess text-mode guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(text_mode_block, text_mode_replacement, 1)

reader_block = '''def reader(proc, output_queue, logfile):\n    try:\n        while True:\n            line = proc.stdout.readline()\n            if line == "":\n                break\n            logfile.write(line)\n            logfile.flush()\n            output_queue.put(line.rstrip("\\n"))\n    finally:\n        output_queue.put(None)\n'''
reader_replacement = '''def reader(proc, output_queue, logfile):\n    try:\n        while True:\n            raw = proc.stdout.readline()\n            if raw == b"" or raw == "":\n                break\n            if isinstance(raw, bytes):\n                line = raw.decode("utf-8", "replace")\n            else:\n                line = raw\n            logfile.write(line)\n            logfile.flush()\n            output_queue.put(line.rstrip("\\n"))\n    finally:\n        output_queue.put(None)\n'''
if reader_block not in source:
    print("R7Q PuTTY shim: reader guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(reader_block, reader_replacement, 1)

log_open_block = '''    with open(logpath, "w") as logfile:\n'''
log_open_replacement = '''    with open(logpath, "w", encoding="utf-8", errors="replace") as logfile:\n'''
if log_open_block not in source:
    print("R7Q PuTTY shim: logfile encoding guard not found; refusing stale transform.",
          file=sys.stderr)
    sys.exit(1)
source = source.replace(log_open_block, log_open_replacement, 1)

code = compile(source, IMPL, "exec")
globals_dict = {
    "__name__": "__main__",
    "__file__": IMPL,
    "__package__": None,
    "normalize_cli_text": normalize_cli_text,
    "utf8_argv": utf8_argv,
}
exec(code, globals_dict)
