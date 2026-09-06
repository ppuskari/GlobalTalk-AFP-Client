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

## R3 hardware performance result

The 16 KiB R3 build compiled successfully on Debian Jessie and completed the
same PageSpinner transfer on September 6, 2026.

Measured from the benchmark start time to the completed transfer log mtime:

- elapsed time: `434` seconds (`7m14s`)
- effective resource rate: `6.00 KiB/s`
- effective resource rate: `49.18 kbit/s`

This is approximately a 2.5x end-to-end throughput improvement over the R2F
baseline while keeping the proven 4624-byte ASP transaction ceiling unchanged.
The observed receive graph also showed denser, higher bursts with less idle
time between them, consistent with the reduction from 652 to 163 path-based
resource-fork requests.

The first R3 benchmark wrapper invocation completed the AFP transfer but its
post-processing exited on Jessie because the script was launched through
`/bin/sh` and used Bash-only `PIPESTATUS`. The wrapper has since been fixed to
re-exec itself under Bash when invoked with `sh`; this wrapper defect did not
change the AFP transfer binary or the measured transfer itself.

Final structural verification of the exact R3 output should still confirm the
same R2F AppleDouble invariants: 2669024 total bytes and resource entry ID 2,
offset 741, length 2668283.

## Write path

ASP `Write` / `WriteContinue` transport support is implemented in the R2/R3
transport layer, including server `ASPFUNC_WRTCONT` handling and multi-packet
ATP responses. Hardware write/upload validation remains pending and is the
next major protocol gate after R3 read/performance regression testing.

## Remaining validation before promotion

1. Confirm the completed R3 PageSpinner file has the exact 2669024-byte
   AppleDouble result and resource entry ID 2 / offset 741 / length 2668283.
2. Pull ordinary data-fork files and verify byte identity.
3. Pull small, boundary-size, and large resource forks.
4. Exercise recursive directory copies with mixed data/resource forks.
5. Verify FinderInfo behavior through a local Netatalk round trip.
6. Hardware-test AFP writes, including payloads crossing 578 and 4624 bytes.
7. After those gates pass, promote the integration branch into the normal
   project build/mainline and retire test-only R2 diagnostic entrypoints.
