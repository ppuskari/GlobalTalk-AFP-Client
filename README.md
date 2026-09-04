# GlobalTalk AFP Client

AFP-over-DDP/ASP transport for **Netatalk Client 0.9.5**, aimed at classic
AppleTalk/GlobalTalk AFP servers that do not expose AFP-over-TCP.

The design keeps Netatalk Client's AFP command serializers, reply parsers,
recursive copy logic, resource-fork handling, FinderInfo handling, and
metadata writers. This project replaces only the DSI/TCP transport path when
an `afp+ddp://` URL is used.

## Phase 1 target

Phase 1 is deliberately an archive/pull client:

- NBP lookup of `Object:AFPServer@Zone`
- ASP GetStatus over ATP/DDP
- ASP OpenSession
- AFP guest (`No User Authent`) login
- volume enumeration/open
- directory enumeration
- data-fork and resource-fork reads
- recursive `afpcmd get`
- Netatalk Client 0.9.5 metadata modes, including Netatalk AppleDouble
- clean AFP logout / ASP close

The transport is synchronous on purpose. This is ideal for `afpcmd` and
archive crawling, and keeps the first GlobalTalk hardware test independent
of the DSI TCP receive loop.

Classic ASP carries at most eight 578-byte response payloads per ATP
transaction, so Phase 1 advertises a 4624-byte receive quantum. Netatalk
Client can then chunk larger fork reads.

Large client-to-server writes requiring ASP Write/WriteContinue are a later
phase. They are not required to archive data from remote guest servers.

## Linux VM prerequisites

- working kernel AppleTalk (`AF_APPLETALK`)
- Netatalk 4.5.1 built with AppleTalk support
- installed `libatalk` and Netatalk headers
- Meson, Ninja, a C compiler, Git and Python 3
- normal Netatalk Client 0.9.5 build dependencies

## Build

```sh
git clone https://github.com/ppuskari/GlobalTalk-AFP-Client.git
cd GlobalTalk-AFP-Client

./scripts/bootstrap-linux.sh
./scripts/build-linux.sh
```

The patched Netatalk Client checkout is created in:

```text
work/netatalk-client
```

## DDP URL syntax

Phase 1 is guest oriented:

```text
afp+ddp://OBJECT@ZONE/VOLUME/path
```

Example:

```sh
./work/netatalk-client/build/cmdline/afpcmd \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global'
```

If the zone is omitted, `*` is used:

```sh
./work/netatalk-client/build/cmdline/afpcmd \
  'afp+ddp://BLIHNMNTE01'
```

## First hardware validation

```sh
nbplkup '=:AFPServer@HuskyNet Global'

./scripts/test-globaltalk.sh \
  'BLIHNMNTE01' \
  'HuskyNet Global'
```

Initial success gate:

1. NBP resolves the server.
2. ASP GetStatus returns a parseable AFP status block.
3. ASP OpenSession returns a session socket and SID.
4. guest FPLogin succeeds.
5. FPGetSrvrParms lists volumes.

After that, a full recursive archival pull can be done directly in batch mode:

```sh
./work/netatalk-client/build/cmdline/afpcmd \
  -r -V -M netatalk \
  'afp+ddp://BLIHNMNTE01@HuskyNet Global/VOLUME/remote/path' \
  /srv/netatalk/archive
```

`-r` is recursive and `-M netatalk` writes FinderInfo, ResourceFork and
extended-attribute metadata using Netatalk's `.AppleDouble/name` and
`name::EA` representation.  That is the mode to use when the destination
directory is then exported by the local Netatalk server.

## Provenance

The adapter targets Netatalk Client 0.9.5 and links against Netatalk 4.5.1
`libatalk` for NBP and ATP. See `docs/ARCHITECTURE.md`.
