#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Summarize R7M stage timings from a captured gt-afp-pull log.
# Python 3.4 compatible.

from __future__ import print_function

import collections
import re
import sys

STAGE_RE = re.compile(r"R7M: stage=([^ ]+).*?elapsed-ms=([0-9]+(?:\.[0-9]+)?)")
SKIP_RE = re.compile(r"R7M: stage=best-effort-close .*?action=skipped")
RECOVERY_RE = re.compile(r"R7I: recovery requested .*?recovery=([0-9]+)/([0-9]+)")
COMPLETE_RE = re.compile(r"Transfer complete\. ([0-9]+) bytes received\.")
EXIT_RE = re.compile(r"gt-afp-pull exit code: ([0-9]+)")


def main():
    if len(sys.argv) != 2:
        print("usage: summarize_r7m_log.py R7M_LOG", file=sys.stderr)
        return 2

    stages = collections.defaultdict(list)
    skipped = 0
    recoveries = 0
    max_cycle = 0
    complete_bytes = None
    exit_code = None

    with open(sys.argv[1], "r", errors="replace") as f:
        for line in f:
            m = STAGE_RE.search(line)
            if m:
                stages[m.group(1)].append(float(m.group(2)))
            if SKIP_RE.search(line):
                skipped += 1
            m = RECOVERY_RE.search(line)
            if m:
                recoveries += 1
                max_cycle = max(max_cycle, int(m.group(1)))
            m = COMPLETE_RE.search(line)
            if m:
                complete_bytes = int(m.group(1))
            m = EXIT_RE.search(line)
            if m:
                exit_code = int(m.group(1))

    print("R7M recovery timing summary")
    print("  recovery cycles requested: {}".format(recoveries))
    print("  highest cycle used:        {}".format(max_cycle))
    print("  poisoned closes skipped:   {}".format(skipped))
    if complete_bytes is not None:
        print("  transfer bytes:            {}".format(complete_bytes))
    if exit_code is not None:
        print("  exit code:                 {}".format(exit_code))
    print()
    print("Stage                        count      total ms        avg ms        max ms")
    print("---------------------------  -----  ------------  ------------  ------------")
    for stage in sorted(stages):
        vals = stages[stage]
        print("{:<27}  {:>5}  {:>12.3f}  {:>12.3f}  {:>12.3f}".format(
            stage, len(vals), sum(vals), sum(vals) / len(vals), max(vals)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
