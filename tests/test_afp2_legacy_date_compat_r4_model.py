#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import calendar
import datetime

AFP_DATE_DELTA = 946684800
LEGACY_ERA_OFFSET = 2209075200
MIN_UNIX = 946684800
MAX_UNIX = 2208988800


def unix_utc(year, month, day, hour, minute, second):
    return calendar.timegm(datetime.datetime(
        year, month, day, hour, minute, second).timetuple())


def signed32(value):
    value &= 0xffffffff
    if value & 0x80000000:
        return value - 0x100000000
    return value


def standards_decode(raw, offset):
    return signed32(raw) + AFP_DATE_DELTA - offset


def compat_decode(raw, offset, enabled):
    standard = standards_decode(raw, 0)

    if enabled and (raw & 0x80000000) and standard < MIN_UNIX:
        alternate = raw - LEGACY_ERA_OFFSET - offset
        if MIN_UNIX <= alternate < MAX_UNIX:
            return alternate

    return standard - offset


def main():
    offset = 39

    create_raw = 0xe393b0b6
    modify_raw = 0xe3defff0

    assert standards_decode(create_raw, offset) == 469824527
    assert standards_decode(modify_raw, offset) == 474760009

    create_compat = compat_decode(create_raw, offset, True)
    modify_compat = compat_decode(modify_raw, offset, True)

    assert create_compat == unix_utc(2020, 12, 27, 1, 17, 3)
    assert modify_compat == unix_utc(2021, 2, 22, 4, 15, 5)

    assert compat_decode(create_raw, offset, False) == 469824527

    # A normal positive AFP date remains untouched.
    normal_raw = 0x32349084
    assert compat_decode(normal_raw, offset, True) == \
        standards_decode(normal_raw, offset)

    # A high-bit value whose alternate does not land in the modern window
    # remains standards-decoded rather than being force-remapped.
    ancient_raw = 0x80000001
    assert compat_decode(ancient_raw, offset, True) == \
        standards_decode(ancient_raw, offset)

    print("AFP 2.x legacy date compatibility R4 model: PASS")
    print("  standards decode remains default: PASS")
    print("  Cloudberry creation date -> 2020-12-27 01:17:03 UTC: PASS")
    print("  Cloudberry modification date -> 2021-02-22 04:15:05 UTC: PASS")
    print("  normal AFP dates remain unchanged: PASS")
    print("  out-of-window high-bit dates remain unchanged: PASS")


if __name__ == "__main__":
    main()
