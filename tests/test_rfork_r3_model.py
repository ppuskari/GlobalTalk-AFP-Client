#!/usr/bin/env python3
from __future__ import print_function

ASP_MAX_DATA = 4624
OLD_METADATA_CHUNK = 4096
R3_METADATA_CHUNK = 32768
IPC_MAX_RESPONSE = 65535 + 1024
PAGESPINNER_RSRC = 2668283
PAGESPINNER_AD_OFFSET = 741
PAGESPINNER_AD_SIZE = 2669024


def ceil_div(a, b):
    return (a + b - 1) // b


def main():
    assert R3_METADATA_CHUNK > OLD_METADATA_CHUNK
    assert R3_METADATA_CHUNK < IPC_MAX_RESPONSE
    assert R3_METADATA_CHUNK > ASP_MAX_DATA
    assert PAGESPINNER_AD_OFFSET + PAGESPINNER_RSRC == PAGESPINNER_AD_SIZE

    old_calls = ceil_div(PAGESPINNER_RSRC, OLD_METADATA_CHUNK)
    r3_calls = ceil_div(PAGESPINNER_RSRC, R3_METADATA_CHUNK)
    assert r3_calls < old_calls
    assert r3_calls * 8 <= old_calls + 8

    asp_reads_per_full_batch = ceil_div(R3_METADATA_CHUNK, ASP_MAX_DATA)
    assert asp_reads_per_full_batch == 8

    print("PASS: R3 batching model")
    print("  old metadata requests: %d" % old_calls)
    print("  R3 metadata requests:  %d" % r3_calls)
    print("  ASP reads/full batch:  %d" % asp_reads_per_full_batch)


if __name__ == "__main__":
    main()
