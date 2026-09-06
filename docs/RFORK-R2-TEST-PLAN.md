# ASP resource-fork R2 test plan

## Gate A - build and linkage

Run:

```sh
sh scripts/build-rfork-r2.sh
nm build-rfork-r2/gt-afp-pull | grep -E ' atp_rsel$| atp_rsel_legacy$'
```

Both `atp_rsel` and `atp_rsel_legacy` should be present, proving that the
private ATP-R1 archive was linked.

## Gate B - basic AFP-over-DDP regression

Before testing metadata, confirm that R2 still completes:

1. NBP server discovery.
2. ASP GetStatus.
3. ASP OpenSession.
4. guest FPLogin.
5. volume open and directory enumeration.
6. ordinary data-fork pull.
7. clean logout / session close.

## Gate C - resource fork read

Choose a file whose AFP resource-fork length is known and preferably exceeds
4624 bytes. Pull with `-M netatalk` and record:

- reported remote resource-fork length;
- destination AppleDouble resource entry length;
- SHA-256 of the resource bytes if an independent source copy is available.

Important R2 expectation: receiving less than the requested count together
with `kFPNoErr` must not terminate the fork. The read loop continues until the
advertised bytes are consumed or AFP explicitly reports `kFPEOFErr`.

Useful boundary sizes when available:

- 1 byte
- 577, 578, 579 bytes
- 4623, 4624, 4625 bytes
- 9248+ bytes

## Gate D - FinderInfo

Verify that type, creator, flags and icon behavior survive a round trip through
the local Netatalk server. FinderInfo must not be sourced from resource-fork
bytes; it remains the 32-byte `kFPFinderInfoBit` metadata object.

## Gate E - ASP FPWrite / WriteContinue

R2 includes the write path even though the current batch utility is pull-first.
When exercising a write-capable client path, test payload boundaries:

- 1, 577, 578, 579 bytes
- 4623 and 4624 bytes
- greater than 4624 bytes (must become multiple FPWrite operations in
  Netatalk Client's `ll_write()` loop)

For each operation confirm that the FPWrite reply offset advances by exactly
the bytes returned through WriteContinue.

## Failure data to capture

If hardware validation fails, save:

```sh
uname -a
ldd build-rfork-r2/gt-afp-pull || true
nm build-rfork-r2/gt-afp-pull | grep -E 'atp_rsel|asp_transport'
nbplkup '=:AFPServer@ZONE'
```

and the verbose client output around the first failed file/fork.
