#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Decode Netatalk AppleDouble File Dates Info (entry ID 8) without requiring
# shell-safe filenames.  Pass a .AppleDouble directory or one sidecar file.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import datetime
import os
import struct
import sys

AD_MAGIC = 0x00051607
AD_HEADER = 26
AD_ENTRY = 12
AD_FILEDATES_ID = 8
AD_DATE_DELTA = 946684800


def decode_unix(raw):
    # Match Netatalk's 32-bit AD_DATE_TO_UNIX arithmetic.
    return (raw + AD_DATE_DELTA) & 0xffffffff


def format_date(raw):
    if raw == 0:
        return "UNSET/ZERO (decodes as 2000-01-01 00:00:00 UTC)"

    value = decode_unix(raw)

    try:
        return datetime.datetime.utcfromtimestamp(value).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OverflowError, OSError):
        return "unix={}".format(value)


def decode_file(path):
    with open(path, "rb") as f:
        header = f.read(AD_HEADER)

        if len(header) != AD_HEADER:
            return

        magic, version = struct.unpack(">II", header[:8])

        if magic != AD_MAGIC:
            return

        count = struct.unpack(">H", header[24:26])[0]

        print()
        print("==================================================")
        print("FILE:", repr(os.path.basename(path)))
        print("size:", os.path.getsize(path))
        print("magic:   0x{:08x}".format(magic))
        print("version: 0x{:08x}".format(version))
        print("entries:", count)

        dates_entry = None

        for i in range(count):
            f.seek(AD_HEADER + i * AD_ENTRY)
            raw_entry = f.read(AD_ENTRY)

            if len(raw_entry) != AD_ENTRY:
                break

            eid, off, length = struct.unpack(">III", raw_entry)
            print("  id={:<10} offset={:<8} length={}".format(
                eid, off, length))

            if eid == AD_FILEDATES_ID and length >= 16:
                dates_entry = (off, length)

        if dates_entry is None:
            print("NO FILE-DATES ENTRY")
            return

        off, length = dates_entry
        f.seek(off)
        raw_dates = f.read(16)

        if len(raw_dates) != 16:
            print("TRUNCATED FILE-DATES ENTRY")
            return

        dates = struct.unpack(">IIII", raw_dates)
        labels = ("Created ", "Modified", "Backup  ", "Access  ")

        print()
        print("Date entry ID 8, offset {}, length {}".format(off, length))
        print("raw:", " ".join("{:08x}".format(value) for value in dates))

        for label, value in zip(labels, dates):
            print("  {}: 0x{:08x}  {}".format(
                label, value, format_date(value)))


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: decode_netatalk_filedates.py SIDECAR_OR_APPLEDOUBLE_DIR")

    target = os.path.abspath(sys.argv[1])

    if os.path.isdir(target):
        for name in sorted(os.listdir(target)):
            path = os.path.join(target, name)

            if os.path.isfile(path):
                decode_file(path)
    elif os.path.isfile(target):
        decode_file(target)
    else:
        raise SystemExit("not found: {}".format(target))


if __name__ == "__main__":
    main()
