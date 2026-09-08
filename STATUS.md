# GlobalTalk AFP Client status

## Hardware-proven AFP-over-DDP read path

Hardware validation on September 6, 2026 proved the legacy AppleTalk
DDP/ATP/ASP path against the AFP 2.1 server `Blackbird` in zone `BaroNet`.

The R2F correctness build successfully retrieved PageSpinner using:

`afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac/The Software!!/PageSpinner 3.0.2/PageSpinner`

Observed final result:

- client exit code: `0`
- data fork: `0` bytes, as expected for this application
- remote resource fork length: `2668283` bytes
- Netatalk AppleDouble sidecar: `2669024` bytes
- AppleDouble magic: `0x00051607`
- AppleDouble version: `0x00020000`
- resource entry: ID `2`, offset `741`, length `2668283`

The sidecar size is exact: `741 + 2668283 = 2669024`.

## Correctness fixes now proven

- `afp+ddp://OBJECT@ZONE/VOLUME/path` discovery and rooted path traversal
- NBP lookup and ASP session establishment
- guest AFP login and volume/path traversal
- up to eight ATP response packets per ASP command
- AFP 2.x 32-bit resource-fork length discovery
- resource-vs-data fork selection through `FPOpenFork`
- preservation of `fp->resource` across the AFP 2.x pre-open parameter query
- short successful `kFPNoErr` reads continue; only explicit `kFPEOFErr` ends a fork
- FinderInfo retrieval and Netatalk AppleDouble construction
- large resource-fork retrieval far beyond the 4624-byte ASP response ceiling
- private libatalk ATP retry-exhaustion shim without modifying system libatalk

## R3 integration candidate

Branch: `integration/rfork-r3-20260906`

Build: `scripts/build-rfork-r3.sh`

R3 folds the hardware-proven R2F corrections into production-named patchers
and removes the R2B/R2C/R2D/R2E diagnostic overlays from the build path.
It raises the stateless metadata batch from 4096 to 16384 bytes while leaving
the ASP wire response ceiling at 4624 bytes.

The 16384-byte batch is deliberately tied to the pinned Netatalk Client 0.9.5
`MAX_CLIENT_RESPONSE` value. The 0.9.5 stateless client separately reserves a
4096-byte log buffer plus framing slack, so R3 does not rely on the larger IPC
framing used by newer Netatalk Client revisions.

The purpose is to reduce repeated path-based resource-fork open/query/close
cycles. For the 2668283-byte PageSpinner resource fork, the metadata layer
needs 652 requests at 4096 bytes but only 163 requests at 16384 bytes. Each
full R3 batch is still serviced internally by ordinary ASP transactions,
requiring four reads for a 16 KiB batch.

## R2F performance baseline

The PageSpinner R2F transfer showed visible 4096-byte growth steps and
receive traffic that was bursty rather than sustained. The complete resource
fork took roughly 18 minutes, corresponding to about 20 kbit/s effective
resource payload throughput, while instantaneous AppleTalk receive bursts
were observed from idle up to roughly 72 kbit/s.

## R3 hardware correctness and performance result

The 16 KiB R3 build compiled successfully on Debian Jessie and completed the
same PageSpinner transfer on September 6, 2026.

Measured from the benchmark start time to the completed transfer log mtime:

- elapsed time: `434` seconds (`7m14s`)
- effective resource rate: `6.00 KiB/s`
- effective resource rate: `49.18 kbit/s`
- final data fork: `0` bytes
- final AppleDouble sidecar: `2669024` bytes
- AppleDouble resource entry: ID `2`, offset `741`, length `2668283`

The R3 AppleDouble result exactly matches the R2F correctness baseline. The
large-resource-fork correctness and performance gate is therefore complete.
This is approximately a 2.5x end-to-end throughput improvement over R2F while
keeping the proven 4624-byte ASP transaction ceiling unchanged.

The observed receive graph also showed denser, higher bursts with less idle
time between them, consistent with the reduction from 652 to 163 path-based
resource-fork requests.

The first R3 benchmark wrapper invocation completed the AFP transfer but its
post-processing exited on Jessie because the script was launched through
`/bin/sh` and used Bash-only `PIPESTATUS`. The wrapper has since been fixed to
re-exec itself under Bash when invoked with `sh`; this wrapper defect did not
change the AFP transfer binary or the measured transfer itself.

## R3 mixed recursive-tree regression

The R3 read path also completed a recursive pull of:

`afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac/The Software!!/MATM 1.5`

Observed result:

- client exit code: `0`
- elapsed time: `122` seconds
- total data-fork bytes reported by the client: `373530`
- `MATM 1.5` data fork: `365240` bytes
- `MATM 1.5 Readme` data fork: `8290` bytes
- `Register` data fork: `0` bytes
- `.AppleDouble/MATM 1.5`: `305305` bytes
- `.AppleDouble/MATM 1.5 Readme`: `121593` bytes
- `.AppleDouble/Register`: `94842` bytes
- `.AppleDouble/.Parent`: `741` bytes

This proves recursive traversal over a mixed classic-Mac tree containing two
nonzero data forks, one zero-length data fork, and AppleDouble metadata for all
three files. The recursive mixed data/resource-fork regression gate is
therefore complete. Exact source-vs-destination data-fork byte identity remains
a separate validation item until the remote source bytes are independently
hashed or otherwise compared.

## R3 ASP automatic AFP-version compatibility

Hardware validation against `Babylon 5` in zone `BabCom` exposed a classic
mixed-era server behavior: generic automatic version selection failed, while
explicit AFP 1.1, 2.0, 2.1, and 2.2 logins all succeeded over ASP/DDP.

R3 now caps automatic AFP selection for ASP/DDP sessions at the highest
advertised version at or below AFP 2.2. Explicit `-A` selections remain exact,
and non-ASP/TCP behavior is unchanged.

Hardware validation after the fix:

- `gt-afp-ls 'afp+ddp://Babylon 5@BabCom'`: PASS
- volumes enumerated: `Green Sector (ReadOnly)`, `Zocalo (Public)`
- `gt-afp-ls 'afp+ddp://Blackbird@BaroNet'`: PASS
- volume enumerated: `Blackbird Public`

This closes the ASP automatic AFP-version negotiation compatibility gate and
proves that the transport-aware cap fixes Babylon 5 without regressing
Blackbird.

## Independent second-server read regression

The R3/R4 path also completed a plain automatic pull from `Babylon 5`:

`afp+ddp://Babylon 5@BabCom/Green Sector (ReadOnly)/TalkCrawler 1.3`

Observed result:

- data fork: `160512` bytes
- Netatalk AppleDouble sidecar: `205746` bytes
- resource entry: offset `741`, length `205005`
- FinderInfo entry: length `32`
- AppleDouble resource entry ended exactly at EOF

This independently proves NBP discovery, ASP session setup, automatic AFP
version negotiation, volume attach, ordinary data-fork retrieval, resource-fork
retrieval, FinderInfo retrieval, AppleDouble construction and clean shutdown
against a second classic AFP server.

## R4 stateful resource-fork streaming

Branch: `integration/rfork-r4-stream-20260907`

Build: `scripts/build-rfork-r4.sh`

R4 keeps the hardware-proven R3 correctness path but replaces repeated
path-based resource-fork requests with the same stateful lifetime already used
for ordinary data forks:

1. query resource-fork size once
2. open the resource fork once
3. perform repeated stateful reads through the same fork ID
4. close the resource fork once

The client-side stream block is `101728` bytes (`22 * 4624`), deliberately an
exact multiple of the proven ASP response ceiling. This does not enlarge the
ASP wire transaction; it only avoids restarting the metadata path every 16 KiB.

For PageSpinner, the model changes from 163 path/open cycles and 652 ASP reads
to one resource-fork open and 578 ASP reads. `578` is also the mathematical
minimum `ceil(2668283 / 4624)`.

### R4 PageSpinner hardware result

The production R4 build completed the same PageSpinner transfer on September 7,
2026:

- exit code: `0`
- elapsed time: `185` seconds
- effective resource rate: `14.09 KiB/s`
- effective resource rate: `115.39 kbit/s`
- data fork: `0` bytes
- AppleDouble sidecar: `2669024` bytes
- resource entry: offset `741`, length `2668283`

The AppleDouble structure exactly matches R2F and R3. Compared with R3, elapsed
time fell from 434 to 185 seconds and effective throughput increased by about
2.35x.

### Resource/data parity hardware proof

An isolated R4 profiler timed only the stateful resource stream without changing
its behavior.

On `Babylon 5`, the zero-data-fork application `Tools/Trawl (icon mod 2)` had a
`147843`-byte resource fork. The measured R4 stream was:

- total resource stream: `7.357` seconds, `160.76 kbit/s`
- open: `0.394` seconds
- read: `6.754` seconds, approximately `175.1 kbit/s`
- local AppleDouble write: below profiler resolution (`0.000` seconds)
- close: `0.209` seconds

A repeated ordinary data-fork pull of
`Tools/dragthing-29.sit` transferred `2290601` bytes in `108.300` seconds,
approximately `169.2 kbit/s` payload throughput. A similarly sized
`Apps/GraphicConverter4.1DE68K.smi` transfer completed at approximately
`170.8 kbit/s`.

On `Blackbird`, the profiler measured the PageSpinner resource stream as:

- total: `176.122` seconds, `121.20 kbit/s`
- open: `0.604` seconds
- read: `175.216` seconds, approximately `121.8 kbit/s`
- local AppleDouble write: `0.006` seconds
- close: `0.295` seconds

Blackbird's ordinary MATM data-fork transfer was previously about `112.5
kbit/s`. Therefore R4 resource forks now run at ordinary data-fork speed on the
same server. The remaining Blackbird-vs-Babylon throughput difference is a
server/path characteristic rather than a resource-fork slow path in this
client.

The resource-fork performance investigation is closed. The one-open/stateful-
read/one-close R4 architecture is the baseline to preserve.

## R4 promotion candidate and tool cleanup

Branch: `integration/rfork-r4-promotion-20260908`

Build: `scripts/build-rfork-r4c.sh`

This branch starts exactly from the hardware-proven R4 production head and does
not change its protocol or resource-stream behavior. It adds only promotion
validation tooling and presentation cleanup:

- `gt-afp-ls` no longer inherits the interactive `afpcmd` message telling the
  user to run nonexistent `ls` and `cd` commands
- `gt-afp-push` exposes the existing batch PUT path for hardware write testing
- `gt-afp-meta` exposes FinderInfo and resource-fork get/set/remove operations
  for controlled validation

The proven R4 branch remains available unchanged as the rollback baseline.

## Write path

ASP `Write` / `WriteContinue` transport support is implemented in the R2/R3/R4
transport layer, including server `ASPFUNC_WRTCONT` handling and multi-packet
ATP responses. The R4 promotion candidate now exposes this existing path via
`gt-afp-push`; hardware write/upload validation remains pending.

## Remaining validation before promotion

1. Verify ordinary data-fork byte identity against an independently known
   source hash.
2. Exercise controlled resource-fork sizes around the ATP and ASP boundaries,
   especially `1`, `577`, `578`, `579`, `4623`, `4624`, `4625`, `16383`,
   `16384`, and `16385` bytes.
3. Verify the exact 32-byte FinderInfo value through a writable-server round
   trip.
4. Hardware-test AFP writes, including data payloads crossing `578` and `4624`
   bytes and metadata/resource writes using the same controlled corpus.
5. After those gates pass, promote the integration branch into the normal
   project build/mainline and retire test-only R2 diagnostic entrypoints.
