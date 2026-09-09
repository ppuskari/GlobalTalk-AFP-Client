#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Byte-level model for the Netatalk AppleDouble File Dates Info overlay.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import calendar
import datetime
import struct

AD_MAGIC = 0x00051607
AD_VERSION = 0x00020000
AD_DATE_DELTA = 946684800
AD_FILEDATES_ID = 8
AD_FILEDATES_OFFSET = 637
AD_FILEDATES_LEN = 16


def unix_utc(year, month, day, hour, minute, second):
    return calendar.timegm(datetime.datetime(
        year, month, day, hour, minute, second).timetuple())


def from_unix(value):
    return (value - AD_DATE_DELTA) & 0xffffffff


def to_unix(value):
    return (value + AD_DATE_DELTA) & 0xffffffff


def make_sidecar(create_unix, modify_unix):
    data = bytearray(741)
    struct.pack_into(">II", data, 0, AD_MAGIC, AD_VERSION)
    data[8:24] = b"Netatalk        "
    struct.pack_into(">H", data, 24, 13)

    ids = (2, 3, 4, 8, 9, 11, 13, 14, 15,
           0x80444556, 0x80494e4f, 0x8053594e, 0x8053567e)
    offsets = (741, 182, 437, 637, 653, 705, 693,
               689, 685, 713, 721, 729, 737)
    lengths = (0, 0, 200, 16, 32, 8, 0, 4, 4, 8, 8, 8, 4)

    for i, values in enumerate(zip(ids, offsets, lengths)):
        struct.pack_into(">III", data, 26 + i * 12, *values)

    # Model the C overlay: write only create/modify.  Backup/access remain 0.
    struct.pack_into(">II", data, AD_FILEDATES_OFFSET,
                     from_unix(create_unix),
                     from_unix(modify_unix))
    return data


def main():
    # Representative dates from the field failure: both are after the
    # Netatalk 2000 epoch and therefore exercise ordinary positive values.
    create_unix = unix_utc(2020, 12, 27, 2, 17, 0)
    modify_unix = unix_utc(2021, 2, 22, 5, 15, 0)
    data = make_sidecar(create_unix, modify_unix)

    magic, version = struct.unpack_from(">II", data, 0)
    assert magic == AD_MAGIC
    assert version == AD_VERSION

    count = struct.unpack_from(">H", data, 24)[0]
    assert count == 13

    found = None
    for i in range(count):
        entry = struct.unpack_from(">III", data, 26 + i * 12)
        if entry[0] == AD_FILEDATES_ID:
            found = entry
            break

    assert found == (AD_FILEDATES_ID,
                     AD_FILEDATES_OFFSET,
                     AD_FILEDATES_LEN)

    create_raw, modify_raw, backup_raw, access_raw = struct.unpack_from(
        ">IIII", data, AD_FILEDATES_OFFSET)

    assert to_unix(create_raw) == create_unix
    assert to_unix(modify_raw) == modify_unix
    assert backup_raw == 0
    assert access_raw == 0

    # Pre-2000 dates must retain Netatalk's 32-bit two's-complement form.
    old_unix = unix_utc(1985, 1, 16, 13, 36, 26)
    old_raw = from_unix(old_unix)
    assert old_raw & 0x80000000
    assert to_unix(old_raw) == old_unix

    print("Netatalk File Dates R1 model: PASS")
    print("  entry ID 8 offset/length: 637/16")
    print("  create/modify round-trip: PASS")
    print("  pre-2000 two's-complement date: PASS")
    print("  backup/access untouched: PASS")


if __name__ == "__main__":
    main()
