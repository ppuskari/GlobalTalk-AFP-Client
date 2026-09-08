#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Verify the controlled R4 promotion corpus after an AFP write/read round trip.
# Checks ordinary data-fork bytes, resource-fork bytes at every boundary size,
# and the exact 32-byte FinderInfo payload from Netatalk AppleDouble sidecars.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import hashlib
import io
import os
import struct
import sys

SIZES = (1, 577, 578, 579, 4623, 4624, 4625, 16383, 16384, 16385)
AD_MAGIC = 0x00051607
AD_VERSION = 0x00020000
AD_RESOURCE_ID = 2
AD_FINDER_ID = 9


def die(msg):
    raise SystemExit("verify_promotion_roundtrip: " + msg)


def read_binary(path):
    with io.open(path, "rb") as f:
        return f.read()


def sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def find_pulled_root(start):
    start = os.path.abspath(start)
    candidates = []

    for current, dirs, files in os.walk(start):
        rel = os.path.relpath(current, start)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 3:
            dirs[:] = []
            continue
        if "manifest.tsv" in files and ".gt-afp-promotion-corpus" in files:
            candidates.append(current)

    if len(candidates) != 1:
        die("expected exactly one pulled corpus root under {}, found {}"
            .format(start, len(candidates)))
    return candidates[0]


def read_manifest(path):
    rows = []
    with io.open(path, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        if header != ["kind", "size", "path", "sha256"]:
            die("unexpected manifest header")
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) != 4:
                die("malformed manifest row: {}".format(line))
            rows.append((fields[0], int(fields[1]), fields[2], fields[3]))
    return rows


def parse_appledouble(path):
    data = read_binary(path)
    if len(data) < 26:
        die("AppleDouble too short: {}".format(path))

    magic, version = struct.unpack(">II", data[0:8])
    if magic != AD_MAGIC:
        die("bad AppleDouble magic in {}: 0x{:08x}".format(path, magic))
    if version != AD_VERSION:
        die("bad AppleDouble version in {}: 0x{:08x}".format(path, version))

    count = struct.unpack(">H", data[24:26])[0]
    table_end = 26 + count * 12
    if table_end > len(data):
        die("truncated AppleDouble entry table: {}".format(path))

    entries = {}
    for i in range(count):
        pos = 26 + i * 12
        entry_id, offset, length = struct.unpack(">III", data[pos:pos + 12])
        end = offset + length
        if end > len(data):
            die("AppleDouble entry {} runs past EOF in {}".format(entry_id, path))
        entries[entry_id] = (offset, length, data[offset:end])

    return data, entries


def main():
    if len(sys.argv) != 3:
        die("usage: verify_promotion_roundtrip.py SOURCE_CORPUS PULL_DEST")

    source = os.path.abspath(sys.argv[1])
    pulled = find_pulled_root(sys.argv[2])

    marker = os.path.join(source, ".gt-afp-promotion-corpus")
    if not os.path.isfile(marker):
        die("source is not a promotion corpus: {}".format(source))

    rows = read_manifest(os.path.join(source, "manifest.tsv"))

    checked_data = 0
    for kind, expected_size, relpath, expected_hash in rows:
        source_path = os.path.join(source, relpath)
        pulled_path = os.path.join(pulled, relpath)

        if not os.path.isfile(source_path):
            die("source file missing: {}".format(source_path))
        if not os.path.isfile(pulled_path):
            die("pulled data fork missing: {}".format(pulled_path))

        actual_size = os.path.getsize(pulled_path)
        actual_hash = sha256_file(pulled_path)
        if actual_size != expected_size:
            die("size mismatch for {}: expected {}, got {}"
                .format(relpath, expected_size, actual_size))
        if actual_hash != expected_hash:
            die("SHA-256 mismatch for {}".format(relpath))
        checked_data += 1

    checked_resources = 0
    for size in SIZES:
        target = "rfork-{:05d}".format(size)
        payload_name = "resource-{:05d}.bin".format(size)
        sidecar = os.path.join(pulled, "resource-targets", ".AppleDouble", target)
        expected_path = os.path.join(source, "resource-payloads", payload_name)

        if not os.path.isfile(sidecar):
            die("resource sidecar missing: {}".format(sidecar))

        ad_data, entries = parse_appledouble(sidecar)
        if AD_RESOURCE_ID not in entries:
            die("resource entry missing: {}".format(sidecar))

        offset, length, resource = entries[AD_RESOURCE_ID]
        expected = read_binary(expected_path)
        if length != size:
            die("resource length mismatch for {}: expected {}, got {}"
                .format(target, size, length))
        if resource != expected:
            die("resource byte mismatch for {}".format(target))
        if offset + length != len(ad_data):
            die("resource entry does not end at AppleDouble EOF for {}"
                .format(target))
        checked_resources += 1

    finder_sidecar = os.path.join(pulled, ".AppleDouble", "finder-target")
    if not os.path.isfile(finder_sidecar):
        die("FinderInfo sidecar missing: {}".format(finder_sidecar))

    ad_data, entries = parse_appledouble(finder_sidecar)
    if AD_FINDER_ID not in entries:
        die("FinderInfo entry missing")

    finder_offset, finder_length, finder = entries[AD_FINDER_ID]
    expected_finder = read_binary(os.path.join(source, "finderinfo.bin"))
    if finder_length != 32:
        die("FinderInfo length mismatch: expected 32, got {}".format(finder_length))
    if finder != expected_finder:
        die("FinderInfo bytes changed during round trip")

    print("PASS: controlled AFP-over-DDP promotion round trip")
    print("  source corpus:       {}".format(source))
    print("  pulled corpus:       {}".format(pulled))
    print("  data files verified: {}".format(checked_data))
    print("  resource forks:      {} boundary sizes byte-exact".format(checked_resources))
    print("  FinderInfo:          32 bytes byte-exact")
    print("  ATP boundary:        577 / 578 / 579 covered")
    print("  ASP boundary:        4623 / 4624 / 4625 covered")
    print("  metadata boundary:   16383 / 16384 / 16385 covered")


if __name__ == "__main__":
    main()
