#!/usr/bin/env python3
from __future__ import print_function

ASP_BODY = 578
ASP_PACKETS = 8
ASP_MAX = ASP_BODY * ASP_PACKETS


def split_write(n):
    assert 0 <= n <= ASP_MAX
    out = []
    left = n
    if left == 0:
        return [0]
    while left:
        take = min(ASP_BODY, left)
        out.append(take)
        left -= take
    return out


def short_read_loop(chunks, requested):
    """Chunks are (result, bytes). Only EOF result establishes EOF."""
    got = 0
    eof = False
    for result, n in chunks:
        if result not in (0, -5009):
            raise RuntimeError(result)
        got += n
        if result == -5009:
            eof = True
            break
        if n == 0:
            break
        if got >= requested:
            break
    return got, eof


assert ASP_MAX == 4624
assert split_write(1) == [1]
assert split_write(578) == [578]
assert split_write(579) == [578, 1]
assert split_write(4624) == [578] * 8

# A short successful response is deliberately not EOF.
got, eof = short_read_loop([(0, 1000), (0, 1000), (0, 1000),
                            (0, 1000), (0, 624)], 4624)
assert got == 4624 and not eof

# Explicit EOF may include final bytes.
got, eof = short_read_loop([(0, 4624), (-5009, 376)], 5000)
assert got == 5000 and eof

print("PASS: ASP R2 wire model")
