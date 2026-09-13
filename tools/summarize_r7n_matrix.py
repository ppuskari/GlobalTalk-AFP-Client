#!/usr/bin/env python3
from __future__ import print_function

import io
import os
import re
import sys


def field(text, name):
    m = re.search(r"^" + re.escape(name) + r"\s*:\s*(.*)$", text,
                  re.MULTILINE)
    return m.group(1).strip() if m else "-"


def count(text, token):
    return text.count(token)


def summarize(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    m = re.search(r"Transfer complete\.\s+(\d+) bytes received\.", text)
    total_bytes = m.group(1) if m else "-"

    m = re.search(r"gt-afp-pull exit code:\s*(-?\d+)", text)
    exit_code = m.group(1) if m else "-"

    return {
        "file": os.path.basename(path),
        "server": field(text, "Server label"),
        "mode": field(text, "Mode"),
        "sends": field(text, "ATP sends"),
        "bytes": total_bytes,
        "exit": exit_code,
        "r7i": count(text, "R7I: recovery requested"),
        "r7j": count(text, "R7J: metadata recovery requested"),
        "r7l": count(text, "R7L: validation stat transient; retrying recovery"),
        "unrec": count(text, "R7I: unrecovered file failure"),
        "idfail": count(text, "R7I.2: resume identity mismatch"),
        "budget": count(text, "recovery budget exhausted"),
    }


def main():
    if len(sys.argv) < 2:
        print("usage: summarize_r7n_matrix.py LOG [LOG ...]", file=sys.stderr)
        return 2

    rows = [summarize(path) for path in sys.argv[1:]]

    print("R7N cross-server summary")
    print("server | mode | sends | exit | bytes | R7I | R7J | R7L2 | unrec | idfail | budget")
    print("-------|------|-------|------|-------|-----|-----|------|-------|--------|-------")
    for row in rows:
        print("{server} | {mode} | {sends} | {exit} | {bytes} | {r7i} | {r7j} | {r7l} | {unrec} | {idfail} | {budget}".format(**row))

    bad = [r for r in rows if r["exit"] != "0" or r["unrec"] or
           r["idfail"] or r["budget"]]
    print()
    if bad:
        print("Candidate gate: NOT CLEAN")
        return 1

    print("Candidate gate: all supplied logs completed without unrecovered, identity, or budget failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
