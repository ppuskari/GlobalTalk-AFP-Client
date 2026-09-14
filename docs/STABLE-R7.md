# GlobalTalk AFP Client Stable R7

Stable R7 is the operator-facing baseline for browsing and downloading AFP
content over classic AppleTalk/GlobalTalk.

## Locked compatibility profile

The stable wrappers always use:

- 7 total ATP sends
- 2-second ATP retry timer
- 50 ms post-object pacing
- R7L bounded six-cycle data-fork recovery
- R7J bounded metadata recovery
- R7I.2 nonzero CNID + exact data-fork size resume identity
- R7M recovery timing retained for diagnostics
- poisoned-session close skipping disabled
- Netatalk metadata mode

The 6-send trial completed but produced materially more recovery activity on
the classic LisaGaming server.  It is not the stable default.

## Build

From the repository root:

```sh
git status --short
sh scripts/build-stable-r7.sh
```

Stable binaries are placed in:

```text
build-stable-r7/afpsld
build-stable-r7/gt-afp-ls
build-stable-r7/gt-afp-pull
build-stable-r7/gt-afp-push
build-stable-r7/gt-afp-meta
```

## Recommended interactive workflow

Run:

```sh
./scripts/gt-afp-browser.sh
```

The browser walks the network in this order:

```text
AppleTalk zone
  -> AFP server
    -> AFP share/volume
      -> directory
        -> file or directory to download
```

Browser commands inside a share:

```text
number   enter a directory
d        download the current directory
g N      download numbered file or directory
u        go up
c        toggle classic Finder date compatibility
q        back out one selector level
```

The selected file/directory name is retained as the default destination leaf.
For example, selecting `PageSpinner 3.0.2` defaults to:

```text
/mnt/AFPSERVER/128G2/AFPFILES2/PageSpinner 3.0.2
```

Press Enter to accept the default or type another local destination.

No destination parent directory is created by the stable pull wrapper.  The
configured parent must already exist.

## Direct pull without the selector

### Directory using the default destination root

```sh
python3 scripts/gt-pull-stable.py -r \
  'afp+ddp://OBJECT@ZONE/VOLUME/remote/folder'
```

This defaults to:

```text
/mnt/AFPSERVER/128G2/AFPFILES2/folder
```

### Directory with an explicit local destination

```sh
python3 scripts/gt-pull-stable.py -r \
  --dest '/mnt/AFPSERVER/128G2/AFPFILES2/CopyTest2' \
  'afp+ddp://OBJECT@ZONE/VOLUME/remote/folder'
```

### Single file

Do not use `-r`:

```sh
python3 scripts/gt-pull-stable.py \
  'afp+ddp://OBJECT@ZONE/VOLUME/remote/path/file'
```

### Full raw output while retaining the progress meter

```sh
python3 scripts/gt-pull-stable.py --verbose -r \
  'afp+ddp://OBJECT@ZONE/VOLUME/remote/folder'
```

## Manual discovery commands

List AppleTalk zones:

```sh
getzones
```

List AFP servers in a zone:

```sh
nbplkup '=:AFPServer@ZONE'
```

List server volumes:

```sh
./build-stable-r7/gt-afp-ls \
  'afp+ddp://OBJECT@ZONE'
```

List a volume or nested directory:

```sh
./build-stable-r7/gt-afp-ls \
  'afp+ddp://OBJECT@ZONE/VOLUME/path'
```

## Live progress display

The stable downloader does not perform additional AFP enumeration and does not
walk the destination tree while a copy is running.

It observes only the current local data file and its Netatalk
`.AppleDouble/<name>` sidecar.  The display therefore gives an approximate
combined view of data-fork plus preserved resource/metadata bytes:

```text
[|] 00:01:42 | preserved 12.40 MiB | now 88.20 KiB/s | avg 121.3 KiB/s |
files 37 | PageSpinner | data 100% | sidecar 2.55 MiB | Ctrl-C abort
```

`preserved` includes AppleDouble container overhead and is intentionally an
operator progress number, not a protocol-byte accounting number.

For ordinary data-fork files the meter also shows the data-fork percentage
using the size already supplied by the R7B enumeration path.  Resource-only
files show activity through sidecar growth.

Press Ctrl-C at any time to stop the selected transfer.  The stable wrapper
then resets `afpsld` so the next browser selection starts with a fresh stable
profile.

Raw transfer output is always saved under `logs/` even when the terminal is
showing the compact progress view.

## Manual daemon reset

When switching from an experimental build/profile back to Stable R7:

```sh
./scripts/gt-afp-reset.sh
```

The stable browser and stable pull wrapper also reset the daemon when needed so
that a previous experiment cannot leave a different ATP retry count inherited
by `afpsld`.

## Proven validation state before lock

The stable profile is based on the 7-send / 50-ms R7L/R7M lineage that:

- completed the LisaGaming torture tree at 21,962,741 bytes with exit code 0;
- recovered classic-server data-fork and metadata stalls without an
  unrecovered failure;
- retained strict CNID + fork-size resume validation;
- completed the same corpus from the local afpserver2/Netatalk server with no
  AFP recovery activity;
- showed that the 6-send / 50-ms variant increased recovery frequency on the
  classic server and therefore should not replace 7/50 as the compatibility
  default.

Stable R7 should be treated as a frozen operational baseline.  Future protocol
or recovery experiments should branch from it rather than modifying the stable
branch in place.
