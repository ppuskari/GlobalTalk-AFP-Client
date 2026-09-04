# Phase 1 status

## Implemented in this starter

- `afp+ddp://OBJECT@ZONE/...` URL parser
- NBP lookup for `OBJECT:AFPServer@ZONE`
- local ATP socket allocation
- ASP GetStatus
- ASP OpenSession
- ASP Command framing with SID and sequence number
- up to eight-packet ATP response reassembly
- AFP result-code extraction
- synthetic DSI reply envelope for reuse of Netatalk Client 0.9.5 parsers
- guest/UAM flow through the existing Netatalk Client login implementation
- existing volume enumeration, directory enumeration, fork reads and
  metadata transfer code retained
- clean ASP CloseSession path
- DSI/TCP remains the original code path for ordinary `afp://` URLs

## Deliberately deferred

- ASP Write / WriteContinue for large client-to-server writes
- asynchronous ASP Attention handling
- idle-session workstation-listener/tickle service
- AFP-over-DDP FUSE mounting
- authenticated non-guest UAM validation against classic servers

The archive crawler/puller is the priority. Those deferred pieces are not
required for a continuously active recursive guest download.

## Validation performed here

- protocol framing cross-checked against Netatalk 4.5.1 ASP/ATP source
- Netatalk Client 0.9.5 request/reply seam cross-checked against its tagged
  source
- patcher Python syntax checked
- generated repository structure and scripts checked locally
- phase-1 source statically checked for balanced C delimiters and expected
  transport constants

## Validation that requires the Netatalk VM / GlobalTalk

This environment has no `AF_APPLETALK` interface or route into GlobalTalk,
so the following are intentionally marked **hardware/network pending**:

1. NBP BRRQ traverses jrouter and resolves the chosen AFPServer.
2. ASP GetStatus decodes on a real remote classic server.
3. OpenSession produces a valid server session socket and SID.
4. `No User Authent` guest FPLogin succeeds.
5. FPGetSrvrParms returns the remote volume list.
6. Recursive data-fork transfer is byte-clean.
7. ResourceFork and FinderInfo round-trip through `-M netatalk`.
8. Long transfers remain alive across classic ASP tickle intervals.

The first run should use `-v debug` so the exact failure boundary is obvious.
