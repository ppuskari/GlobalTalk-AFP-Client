# GlobalTalk AFP Client

GlobalTalk AFP Client is an experimental AFP-over-legacy-AppleTalk client path
for modern Linux systems that still need to communicate with classic AFP
servers over DDP/ATP/ASP rather than TCP/IP.

The project combines pinned Netatalk Client 0.9.5 logic with a legacy
libatalk/ASP transport so classic Macintosh AFP servers can be reached through
GlobalTalk-style routed AppleTalk networks.

## Current R3 integration candidate

The current hardware-test branch is:

`integration/rfork-r3-20260906`

Build it on the Jessie/Linux test host with:

```sh
sh scripts/build-rfork-r3.sh
```

The build produces:

- `build-rfork-r3/afpsld`
- `build-rfork-r3/gt-afp-pull`
- `build-rfork-r3/gt-afp-ls`

`gt-afp-ls` is a lightweight server/volume/path browser using the same R3 AFP
connection path. A server-only URL lists available volumes; a URL containing a
volume or nested path lists that directory.

Examples:

```sh
./build-rfork-r3/gt-afp-ls \
  'afp+ddp://Blackbird@BaroNet'

./build-rfork-r3/gt-afp-ls \
  'afp+ddp://Blackbird@BaroNet/Blackbird Public/Pimp My Mac'
```

A recursive pull can be run with:

```sh
./build-rfork-r3/gt-afp-pull -r -V -M netatalk \
  'afp+ddp://Blackbird@BaroNet/Blackbird Public/path' \
  /srv/netatalk/archive
```

## R3 hardware status

The large-resource-fork PageSpinner test is hardware-proven on Debian Jessie
against the AFP 2.1 server `Blackbird` in zone `BaroNet`.

Measured R3 result:

- data fork: `0` bytes
- resource fork: `2668283` bytes
- AppleDouble sidecar: `2669024` bytes
- resource entry: ID `2`, offset `741`, length `2668283`
- elapsed: `434` seconds (`7m14s`)
- effective resource rate: `49.18 kbit/s`

This is about a 2.5x end-to-end improvement over the R2F baseline while
preserving the proven 4624-byte ASP transaction ceiling.

A second recursive regression against `MATM 1.5` also passed with exit code 0,
copying two nonzero data forks, one zero-length data fork, and AppleDouble
metadata/resource forks for all three files. See `STATUS.md` for the exact
sizes and remaining promotion gates.

## Design constraints

The target is intentionally conservative:

- Netatalk Client is pinned to 0.9.5.
- ASP response payload remains limited to 8 ATP responses x 578 bytes = 4624
  bytes.
- R3 uses a 16384-byte stateless metadata batch, matching the pinned 0.9.5
  `MAX_CLIENT_RESPONSE` ceiling.
- The private ATP retry-exhaustion shim is linked into the test tools without
  replacing the system `/usr/local/lib/libatalk.a`.
- The R3 build path excludes the R2B/R2C/R2D/R2E diagnostic overlays.

## Repository safety

The Linux and Windows sync helpers are fast-forward-only and refuse dirty
working trees. They do not reset, clean, or automatically stash local work.

Linux:

```sh
sh scripts/sync-integration-r3.sh
```

Windows PowerShell:

```powershell
.\powershell\Sync-Integration-R3.ps1
```

Default Windows repository location:

`C:\AppleIIgsDev\GlobalTalk-AFP-Client`

## Documentation

See:

- `STATUS.md` for the current hardware-validation ledger.
- `RFORK-R2.md` for the ASP/resource-fork transport work.
- `docs/RFORK-R2-TEST-PLAN.md` for the regression gates.
- `docs/ARCHITECTURE.md` for the project layout.
