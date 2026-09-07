#!/usr/bin/env python3
from __future__ import print_function

import math

PAGE_SPINNER_RESOURCE = 2668283
ASP_RESPONSE = 4624
R3_METADATA = 16384
R4_STREAM = 101728


def ceil_div(a, b):
    return (a + b - 1) // b


def segmented_wire_reads(total, segment, wire):
    full = total // segment
    tail = total % segment
    count = full * ceil_div(segment, wire)
    if tail:
        count += ceil_div(tail, wire)
    return count


def main():
    r3_requests = ceil_div(PAGE_SPINNER_RESOURCE, R3_METADATA)
    r4_requests = ceil_div(PAGE_SPINNER_RESOURCE, R4_STREAM)
    r3_wire = segmented_wire_reads(PAGE_SPINNER_RESOURCE,
                                   R3_METADATA, ASP_RESPONSE)
    r4_wire = segmented_wire_reads(PAGE_SPINNER_RESOURCE,
                                   R4_STREAM, ASP_RESPONSE)
    ideal_wire = ceil_div(PAGE_SPINNER_RESOURCE, ASP_RESPONSE)

    assert R4_STREAM == 22 * ASP_RESPONSE
    assert r3_requests == 163
    assert r4_requests == 27
    assert r3_wire == 652
    assert r4_wire == 578
    assert r4_wire == ideal_wire

    # The key R4 change is fork lifetime, not a larger ASP transaction.
    r3_remote_opens = r3_requests
    r4_remote_opens = 1
    assert r3_remote_opens == 163
    assert r4_remote_opens == 1

    print("PASS: R4 stateful resource-fork streaming model")
    print("  R3 path-based resource requests: %d" % r3_requests)
    print("  R4 stateful read requests:       %d" % r4_requests)
    print("  R3 remote resource opens:        %d" % r3_remote_opens)
    print("  R4 remote resource opens:        %d" % r4_remote_opens)
    print("  R3 ASP read transactions:        %d" % r3_wire)
    print("  R4 ASP read transactions:        %d" % r4_wire)
    print("  Ideal ASP read transactions:     %d" % ideal_wire)


if __name__ == "__main__":
    main()
