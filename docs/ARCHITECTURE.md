# Architecture

## Existing Netatalk Client path

```text
afpcmd / client API
      -> AFP serializers
      -> dsi_send()
      -> DSI/TCP
```

The 0.9.5 AFP reply handlers expect a DSI header at the beginning of
`server->incoming_buffer`. The DDP adapter deliberately preserves that
internal ABI.

## Added DDP path

```text
afpcmd / client API
      -> AFP serializers
      -> dsi_send()
         |-> original DSI/TCP path
         `-> asp_transport_send()
             -> strip DSI envelope
             -> ASP Command
             -> ATP
             -> DDP / GlobalTalk
             -> AFP-over-ASP server
             -> reassemble ASP response
             -> synthesize DSI reply header
             -> existing AFP reply parser
```

This makes DDP a transport adapter, not a second AFP implementation.

## NBP

`afp+ddp://OBJECT@ZONE/...` maps to:

```c
nbp_lookup(object, "AFPServer", zone, ...)
```

The resulting `sockaddr_at` supplies network, node and ASP listener socket.

## ASP OpenSession

The client opens a local ATP socket and sends an ASP OpenSession transaction
to the NBP listener.

Request user bytes:

```text
ASPFUNC_OPEN, client-workstation-socket, 0, 0
```

Successful response user bytes:

```text
server-session-socket, SID, 0, 0
```

Subsequent commands target the returned server session socket.

## ASP Command

Request user bytes:

```text
ASPFUNC_CMD, SID, sequence-hi, sequence-lo
```

The AFP command follows those four bytes.

A response can contain up to eight ATP packets. Each packet contains four
ASP user bytes plus up to 578 bytes of AFP data. The first response packet's
user bytes contain the 32-bit AFP result code.

The adapter strips the per-packet ASP headers, concatenates the AFP payload,
adds a synthetic DSI reply header, and invokes the existing 0.9.5 AFP reply
handler.

## Read sizing

```text
request payload max     578 bytes
response payload max   4624 bytes (8 x 578)
```

Phase 1 advertises those values as the transport quantums so large reads are
split by the existing high-level client.

## Why use libatalk

Netatalk 4.5.1 installs `libatalk` plus the ATP, ASP, NBP and DDP headers when
AppleTalk support is built. Reusing it avoids writing a second ATP state
machine and gives us Netatalk's established transaction IDs, retransmission,
bitmaps and exactly-once behavior.
