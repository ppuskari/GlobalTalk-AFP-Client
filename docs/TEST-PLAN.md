# GlobalTalk hardware test plan

Use a server that is already visible with `nbplkup`.

## Gate 0 - Linux AppleTalk

```sh
getzones | head
nbplkup '=:AFPServer@HuskyNet Global'
```

Expected: at least one `AFPServer` tuple with a DDP network.node:socket.

## Gate 1 - build

```sh
./scripts/bootstrap-linux.sh
./scripts/build-linux.sh
```

Expected: patched Netatalk Client 0.9.5 compiles and links against `libatalk`.

## Gate 2 - status and session

```sh
./work/netatalk-client/build/cmdline/afpcmd \
  -v debug \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global'
```

Transport diagnostics to look for:

```text
DDP NBP resolved BLIHNMNTE01:AFPServer@HuskyNet Global to N.N:S
ASP session open: server socket S, SID I
```

Then the normal Netatalk Client connection should progress through guest
login and server parameters.

## Gate 3 - volume

If a volume is named `Public`:

```sh
./work/netatalk-client/build/cmdline/afpcmd \
  -v debug \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global/Public'
```

At the `afpcmd:` prompt:

```text
ls
```

## Gate 4 - one Macintosh file

Pick a file known to have a non-empty resource fork.

```sh
mkdir -p /tmp/gt-afp-one

./work/netatalk-client/build/cmdline/afpcmd \
  -V -M netatalk \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global/Public/path/File' \
  /tmp/gt-afp-one
```

Inspect:

```sh
find /tmp/gt-afp-one -maxdepth 3 -ls
```

For Netatalk metadata mode, expect the data file plus Netatalk metadata
representation such as `.AppleDouble/<name>` and, when applicable,
`<name>::EA`.

## Gate 5 - recursive directory

```sh
mkdir -p /srv/netatalk/globaltalk-mirror

./work/netatalk-client/build/cmdline/afpcmd \
  -r -V -M netatalk \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global/Public/path/to/folder' \
  /srv/netatalk/globaltalk-mirror
```

## Gate 6 - Mac-side validation

Export the destination with the local Netatalk server and inspect from a
Classic Mac / IIgs:

- Finder icon/type/creator are correct.
- applications/documents that depend on resource forks still open.
- directory hierarchy and names are correct.
- compare representative data and resource fork sizes to the source.

## What to capture on a failure

Run with `-v debug` and retain:

```sh
nbplkup 'SERVER:AFPServer@ZONE'
uname -a
ldconfig -p | grep libatalk
./work/netatalk-client/build/cmdline/afpcmd -v debug \
  'afp+ddp://SERVER@ZONE'
```

The debug boundary tells us whether the next patch belongs to NBP, ATP,
ASP OpenSession, AFP login, volume operations, or the fork transfer path.
