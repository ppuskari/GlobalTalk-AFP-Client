#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Create deterministic local payloads for the final AFP-over-DDP promotion
# gates.  The files deliberately straddle ATP/ASP and metadata batch sizes.
# Debian Jessie / Python 3.4 compatible.

from __future__ import print_function

import hashlib
import io
import os
import shutil
import sys

SIZES = (1, 577, 578, 579, 4623, 4624, 4625, 16383, 16384, 16385)


def die(msg):
    raise SystemExit("make_promotion_corpus: " + msg)


def payload(size, salt):
    # Deterministic, nontrivial pattern.  Do not use all-zero files: byte
    # identity failures at chunk boundaries are easier to detect this way.
    return bytes(bytearray(((i * 131 + size + salt) & 0xff)
                           for i in range(size)))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_binary(path, data):
    with io.open(path, "wb") as f:
        f.write(data)


def main():
    if len(sys.argv) != 2:
        die("usage: make_promotion_corpus.py OUTPUT_DIRECTORY")

    root = os.path.abspath(sys.argv[1])

    if os.path.exists(root):
        # Refuse to destroy an arbitrary populated directory.  A previous
        # corpus created by this tool is safe to replace only when its marker
        # is present.
        marker = os.path.join(root, ".gt-afp-promotion-corpus")
        if not os.path.isfile(marker):
            die("refusing to replace unmarked directory: {}".format(root))
        shutil.rmtree(root)

    data_dir = os.path.join(root, "data")
    resource_dir = os.path.join(root, "resource-payloads")
    os.makedirs(data_dir)
    os.makedirs(resource_dir)

    records = []

    for size in SIZES:
        name = "data-{:05d}.bin".format(size)
        path = os.path.join(data_dir, name)
        value = payload(size, 0x21)
        write_binary(path, value)
        records.append(("data", size, os.path.relpath(path, root), sha256(value)))

    for size in SIZES:
        name = "resource-{:05d}.bin".format(size)
        path = os.path.join(resource_dir, name)
        value = payload(size, 0x63)
        write_binary(path, value)
        records.append(("resource", size, os.path.relpath(path, root), sha256(value)))

    empty_path = os.path.join(root, "empty.bin")
    write_binary(empty_path, b"")
    records.append(("data", 0, "empty.bin", sha256(b"")))

    # Valid, deliberately simple 32-byte FinderInfo: type TEXT, creator ttxt,
    # all Finder flags/location/folder/extended fields zero.
    finder = b"TEXTttxt" + (b"\x00" * 24)
    if len(finder) != 32:
        die("internal FinderInfo length error")
    finder_path = os.path.join(root, "finderinfo.bin")
    write_binary(finder_path, finder)
    records.append(("finderinfo", 32, "finderinfo.bin", sha256(finder)))

    with io.open(os.path.join(root, "manifest.tsv"), "w", encoding="utf-8") as f:
        f.write("kind\tsize\tpath\tsha256\n")
        for kind, size, relpath, digest in records:
            f.write("{}\t{}\t{}\t{}\n".format(kind, size, relpath, digest))

    with io.open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as f:
        f.write("GlobalTalk AFP Client R4 promotion corpus\n")
        f.write("Boundary sizes: {}\n".format(", ".join(str(x) for x in SIZES)))
        f.write("FinderInfo: 32 bytes, type TEXT, creator ttxt\n")
        f.write("All payloads are deterministic; hashes are in manifest.tsv.\n")

    with io.open(os.path.join(root, ".gt-afp-promotion-corpus"), "w",
                 encoding="ascii") as f:
        f.write("R4C\n")

    print("PASS: promotion corpus created")
    print("  root: {}".format(root))
    print("  data boundary files: {}".format(len(SIZES)))
    print("  resource payloads:   {}".format(len(SIZES)))
    print("  FinderInfo bytes:    32")
    print("  manifest:            {}".format(os.path.join(root, "manifest.tsv")))


if __name__ == "__main__":
    main()
