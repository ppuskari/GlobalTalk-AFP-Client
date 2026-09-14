#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# UTF-8-safe launcher for the interactive AFP browser on Python 3.4/Jessie.
# The browser itself stays unchanged; this shim rewrites only subprocess argv
# boundaries so classic Mac filenames are passed as explicit UTF-8 bytes even
# when Python reports an ASCII filesystem encoding.

from __future__ import print_function

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMPL = os.path.join(ROOT, "scripts", "gt-afp-browser.py")


def normalize_text(value):
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
    result = []
    for item in argv:
        if isinstance(item, bytes):
            result.append(item)
        elif isinstance(item, str):
            result.append(normalize_text(item).encode("utf-8"))
        else:
            result.append(item)
    return result


if not os.path.isfile(IMPL):
    print("AFP browser implementation missing: %s" % IMPL, file=sys.stderr)
    sys.exit(1)

with open(IMPL, "r") as handle:
    source = handle.read()

# Zone/server discovery and AFP ls calls all pass through these helpers.
old_check = '''        out = subprocess.check_output(\n            argv, stderr=subprocess.STDOUT, env=env)\n'''
new_check = '''        out = subprocess.check_output(\n            utf8_argv(argv), stderr=subprocess.STDOUT, env=env)\n'''
if old_check not in source:
    print("AFP browser UTF-8 shim: check_output guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old_check, new_check, 1)

old_popen = '''        proc = subprocess.Popen(\n            argv,\n            stdin=subprocess.PIPE,\n'''
new_popen = '''        proc = subprocess.Popen(\n            utf8_argv(argv),\n            stdin=subprocess.PIPE,\n'''
if old_popen not in source:
    print("AFP browser UTF-8 shim: Popen guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old_popen, new_popen, 1)

# Download selections can themselves contain non-ASCII path components.
old_call = '''    rc = subprocess.call(command, env=env)\n'''
new_call = '''    rc = subprocess.call(utf8_argv(command), env=env)\n'''
if old_call not in source:
    print("AFP browser UTF-8 shim: download call guard missing.", file=sys.stderr)
    sys.exit(1)
source = source.replace(old_call, new_call, 1)

code = compile(source, IMPL, "exec")
globals_dict = {
    "__name__": "__main__",
    "__file__": IMPL,
    "__package__": None,
    "normalize_text": normalize_text,
    "utf8_argv": utf8_argv,
}
exec(code, globals_dict)
