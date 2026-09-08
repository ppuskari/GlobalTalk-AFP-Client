#!/usr/bin/env python3
from __future__ import print_function

ASP_MAX_DATA = 4624
OLD_METADATA_CHUNK = 4096
R3_METADATA_CHUNK = 16384
MAX_CLIENT_RESPONSE = 16384
STATELESS_INCOMING_FRAME = 32768
MIN_METADATA_REQUEST_SLACK = 4096
LOG_BUFFER = 4096
RESPONSE_SLACK = 200
PAGESPINNER_RSRC = 2668283
PAGESPINNER_AD_OFFSET = 741
PAGESPINNER_AD_SIZE = 2669024


def ceil_div(a, b):
    return (a + b - 1) // b


def main():
    assert R3_METADATA_CHUNK > OLD_METADATA_CHUNK
    assert R3_METADATA_CHUNK <= MAX_CLIENT_RESPONSE
    assert R3_METADATA_CHUNK > ASP_MAX_DATA
    assert MAX_CLIENT_RESPONSE + LOG_BUFFER + RESPONSE_SLACK > R3_METADATA_CHUNK

    # Read payloads travel in daemon responses, but resource-fork writes carry
    # the metadata payload inside the client->afpsld request.  The command frame
    # must therefore exceed the 16 KiB payload by enough room for the stateless
    # request header, path, name, offset and flags.
    assert STATELESS_INCOMING_FRAME > R3_METADATA_CHUNK
    assert (STATELESS_INCOMING_FRAME - R3_METADATA_CHUNK
            >= MIN_METADATA_REQUEST_SLACK)

    assert PAGESPINNER_AD_OFFSET + PAGESPINNER_RSRC == PAGESPINNER_AD_SIZE

    old_calls = ceil_div(PAGESPINNER_RSRC, OLD_METADATA_CHUNK)
    r3_calls = ceil_div(PAGESPINNER_RSRC, R3_METADATA_CHUNK)
    assert old_calls == 652
    assert r3_calls == 163
    assert r3_calls < old_calls

    asp_reads_per_full_batch = ceil_div(R3_METADATA_CHUNK, ASP_MAX_DATA)
    assert asp_reads_per_full_batch == 4

    print("PASS: R3 batching model")
    print("  old metadata requests: %d" % old_calls)
    print("  R3 metadata requests:  %d" % r3_calls)
    print("  ASP reads/full batch:  %d" % asp_reads_per_full_batch)
    print("  stateless IPC frame:   %d" % STATELESS_INCOMING_FRAME)


if __name__ == "__main__":
    main()
