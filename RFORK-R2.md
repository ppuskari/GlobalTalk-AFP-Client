# ASP resource-fork R2 hardware test

Branch: `test/asp-rfork-r2-20260906`

This revision keeps the existing Netatalk Client 0.9.5 AFP logic and changes
only the classic AppleTalk ASP transport behavior needed for reliable
resource-fork reads and ASP writes with the old libatalk 2.2.4 environment.

## What changes

- ASP receive quantum remains 4624 bytes (`8 * 578`).
- ASP FPWrite transmit quantum becomes 4624 bytes because write data is
  delivered through ASP WriteContinue rather than inside the one-packet AFP
  command request.
- `DSI_DSIWrite` is translated into `ASPFUNC_WRITE` carrying only the AFP
  FPWrite parameter block.
- While FPWrite is outstanding, the client accepts `ASPFUNC_WRTCONT` on the
  same ATP socket and returns up to eight ATP responses. Every response has
  the required four ASP user bytes plus up to 578 bytes of fork data.
- The final AFP FPWrite result and resulting fork offset go back through the
  existing Netatalk Client reply parser.
- Netatalk Client 0.9.5 no longer treats a short successful `kFPNoErr` read as
  EOF. Only explicit `kFPEOFErr` establishes EOF.
- FinderInfo remains the separate 32-byte `kFPFinderInfoBit` AFP metadata
  object. Resource forks remain `FPOpenFork(resource)` plus FPRead/FPWrite.
- AFP 2.x continues to use the existing 32-bit fork-length commands and bits.
- The included ATP-R1 wrapper creates a private archive and never overwrites
  `/usr/local/lib/libatalk.a`.

## Safe Git synchronization

POSIX/Linux:

```sh
sh scripts/sync-rfork-r2.sh /path/to/GlobalTalk-AFP-Client
```

Windows PowerShell 5.1:

```powershell
.\powershell\Sync-RFork-R2.ps1 -Repo 'C:\path\to\GlobalTalk-AFP-Client'
```

Both helpers refuse a dirty tree and use fetch plus fast-forward only. They do
not reset, clean, or automatically stash local work.

## Build on the AppleTalk VM

The Netatalk Client 0.9.5 work tree must have been bootstrapped at least once:

```sh
sh scripts/bootstrap-linux.sh
```

Then:

```sh
python3 tests/test_rfork_r2_model.py
sh scripts/build-rfork-r2.sh
```

Outputs:

```text
build-rfork-r2/afpsld
build-rfork-r2/gt-afp-pull
```

The builder creates and links:

```text
legacy/atalk-r1/libatalk-atp-r1.a
```

from the installed `/usr/local/lib/libatalk.a` without changing the installed
library.

## First resource-fork test

Use a remote file with a known nonzero resource fork, preferably larger than
4624 bytes:

```sh
./build-rfork-r2/gt-afp-pull -r -V -M netatalk \
  'afp+ddp://SERVER@ZONE/VOLUME/path' \
  /srv/netatalk/archive-test
```

Then inspect `.AppleDouble` files and export the destination back through your
local Netatalk server. A Classic Mac / IIgs should see the expected Finder
metadata and resource-based file behavior.

See `docs/RFORK-R2-TEST-PLAN.md` for the boundary tests and failure capture.

## Rollback

R2 patches only the generated `work/netatalk-client` tree during the R2 build.
The tracked Phase-1 overlay is unchanged. To return to the ordinary legacy
build, run:

```sh
sh scripts/build-legacy-afpcmd.sh
```

or switch back to `main` with a normal fast-forward-only update.
