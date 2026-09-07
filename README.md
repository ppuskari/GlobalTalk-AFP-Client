# GlobalTalk AFP Client

AFP-over-DDP/ASP transport for **Netatalk Client 0.9.5**, aimed at classic
AppleTalk/GlobalTalk AFP servers that do not expose AFP-over-TCP.

The design keeps Netatalk Client's AFP command serializers, reply parsers,
recursive copy logic, resource-fork handling, FinderInfo handling, and
metadata writers. This project replaces only the DSI/TCP transport path when
an `afp+ddp://` URL is used.

## Current integration build

The hardware-proven read path is being consolidated on:

```text
integration/rfork-r3-20260906
```

Build on the Debian Jessie / AppleTalk VM with:

```sh
sh scripts/build-rfork-r3.sh
```

This produces:

```text
build-rfork-r3/afpsld
build-rfork-r3/gt-afp-pull
build-rfork-r3/gt-afp-ls
```

R3 includes:

- rooted `afp+ddp://OBJECT@ZONE/VOLUME/path` handling
- NBP lookup and ASP session establishment
- guest AFP login
- eight-packet ATP response reassembly
- correct AFP 2.x data/resource fork selection
- large resource-fork reads
- short-success-not-EOF behavior
- FinderInfo and Netatalk AppleDouble preservation
- private libatalk ATP retry-exhaustion shim
- ASP Write/WriteContinue transport implementation
- 16 KiB stateless metadata batching for lower resource-fork reopen overhead
- lightweight `gt-afp-ls` volume/directory browsing

The ASP wire response ceiling remains **4624 bytes**. The **16384-byte**
metadata batch is capped at Netatalk Client 0.9.5's own
`MAX_CLIENT_RESPONSE`; it only keeps a resource fork open across several
ordinary ASP reads and does not enlarge the AFP/ATP wire transaction.

## Volume and path browser

`gt-afp-ls` uses the same R3 connection/authentication path as `gt-afp-pull`
and reuses Netatalk Client 0.9.5's existing directory-list implementation.
It adds no new AFP transport behavior.

A server-only URL lists available volumes:

```sh
./build-rfork-r3/gt-afp-ls \
  'afp+ddp://Blackbird@BaroNet'
```

A URL containing a volume or nested path lists that directory:

```sh
./build-rfork-r3/gt-afp-ls \
  'afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac'
```

## Hardware validation

On September 6, 2026, R3 successfully retrieved PageSpinner from the AFP 2.1
server `Blackbird` in zone `BaroNet`:

```text
afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac/The Software!!/PageSpinner 3.0.2/PageSpinner
```

The transfer exited cleanly with:

```text
Data fork:                       0 bytes
Remote resource fork:     2668283 bytes
AppleDouble sidecar:       2669024 bytes
Resource entry ID:                2
Resource entry offset:          741
Resource entry length:      2668283
Elapsed:                         434 seconds
Effective resource rate:      49.18 kbit/s
```

The final sidecar size is exact: `741 + 2668283 = 2669024`.
This is about a 2.5x end-to-end throughput improvement over the R2F baseline.

A second recursive hardware regression against:

```text
afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac/The Software!!/MATM 1.5
```

also passed with exit code 0. It copied two nonzero data forks, one zero-length
data fork, and AppleDouble metadata/resource forks for all three files. See
`STATUS.md` for exact sizes and the remaining promotion gates.

## Linux VM prerequisites

- working kernel AppleTalk (`AF_APPLETALK`)
- Netatalk built with AppleTalk support
- installed `libatalk` and Netatalk headers
- a C compiler, Git and Python 3
- Debian Jessie / Python 3.4 remains supported by the integration patchers

## Bootstrap

A fresh Netatalk Client 0.9.5 work tree can be prepared with:

```sh
sh scripts/bootstrap-linux.sh
```

The patched checkout is created in:

```text
work/netatalk-client
```

The bootstrap canonicalizes the hardware-proven rooted DDP pathname form.

## DDP URL syntax

Guest-oriented URL syntax:

```text
afp+ddp://OBJECT@ZONE/VOLUME/path
```

If the zone is omitted, `*` is used.

Example:

```sh
./build-rfork-r3/gt-afp-pull \
  -r -V -M netatalk \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global/VOLUME/remote/path' \
  /srv/netatalk/archive
```

`-r` is recursive and `-M netatalk` writes FinderInfo, ResourceFork and
extended-attribute metadata using Netatalk's `.AppleDouble/name` and
`name::EA` representation.

## Performance benchmark

The R2F PageSpinner transfer exposed a 4096-byte metadata staircase and
roughly 20 kbit/s effective resource payload throughput, with receive bursts
up to roughly 72 kbit/s. R3 batches 16384 bytes per stateless metadata request
to reduce repeated remote fork opens. For PageSpinner that reduces the
path-based resource requests from 652 to 163 while retaining normal 4624-byte
ASP reads.

Run the exact PageSpinner correctness/performance benchmark with:

```sh
sh scripts/benchmark-pagespinner-r3.sh
```

The benchmark requires the exact final AppleDouble structure and reports
elapsed time plus effective resource-fork KiB/s and kbit/s.

## Safe local synchronization

Linux:

```sh
sh scripts/sync-integration-r3.sh
```

Windows PowerShell 5.1, defaulting to
`C:\AppleIIgsDev\GlobalTalk-AFP-Client`:

```powershell
.\powershell\Sync-Integration-R3.ps1
```

Both sync paths refuse dirty work trees and use fast-forward-only Git updates.
They never run `git reset --hard` or `git clean`.

## Write path

ASP `Write` / `WriteContinue` support is implemented, including server
`ASPFUNC_WRTCONT` requests and multi-packet ATP responses. Hardware
write/upload validation is still pending and follows the remaining R3 read
regression gates.

## Provenance

The adapter targets Netatalk Client 0.9.5 and links against Netatalk
`libatalk` for NBP and ATP. See `docs/ARCHITECTURE.md`.
