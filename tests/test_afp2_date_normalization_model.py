#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Model the AFP 2.x server-clock normalization backported from newer
# Netatalk Client.  Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import calendar
import datetime

AD_DATE_DELTA = 946684800
U32 = 0xffffffff


def unix_utc(year, month, day, hour, minute, second):
    return calendar.timegm(datetime.datetime(
        year, month, day, hour, minute, second).timetuple())


def wire_from_clock(value):
    return (value - AD_DATE_DELTA) & U32


def raw_clock_from_wire(value):
    seconds = value & U32
    if seconds & 0x80000000:
        seconds -= 0x100000000
    return seconds + AD_DATE_DELTA


def normalize_afp2(wire_value, server_offset):
    return raw_clock_from_wire(wire_value) - server_offset


def main():
    # Field-shaped case from Cloudberry.  The raw AFP create value decoded by
    # the old 0.9.5 path as 1984-11-20 18:49:26 UTC, while Finder reports the
    # same file in late 2020.  A decades-wide server clock error is legitimate
    # input to this algorithm and must NOT be clamped like a timezone offset.
    desired_create = unix_utc(2020, 12, 27, 2, 17, 0)
    desired_modify = unix_utc(2021, 2, 22, 5, 15, 2)
    server_offset = -1139210854

    raw_create = desired_create + server_offset
    raw_modify = desired_modify + server_offset

    assert raw_create == unix_utc(1984, 11, 20, 18, 49, 26)
    assert raw_modify == unix_utc(1985, 1, 16, 21, 47, 28)

    create_wire = wire_from_clock(raw_create)
    modify_wire = wire_from_clock(raw_modify)

    # Both are pre-2000 signed AFP date values.
    assert create_wire & 0x80000000
    assert modify_wire & 0x80000000

    assert normalize_afp2(create_wire, server_offset) == desired_create
    assert normalize_afp2(modify_wire, server_offset) == desired_modify

    # The offset is derived from FPGetSrvrParms server-now minus client-now.
    client_now = unix_utc(2026, 9, 9, 20, 35, 0)
    server_now = client_now + server_offset
    measured_offset = server_now - client_now
    assert measured_offset == server_offset

    # AFP 3.x has UTC dates and therefore does not apply the AFP 2.x offset.
    modern_wire = wire_from_clock(desired_modify)
    assert raw_clock_from_wire(modern_wire) == desired_modify

    print("AFP 2.x date normalization R1 model: PASS")
    print("  signed pre-2000 wire dates: PASS")
    print("  FPGetSrvrParms clock offset: PASS")
    print("  decades-wide server clock correction: PASS")
    print("  AFP 3.x no-offset control: PASS")


if __name__ == "__main__":
    main()
