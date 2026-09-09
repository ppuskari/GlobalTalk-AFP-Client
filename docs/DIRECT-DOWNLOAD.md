# Direct AFP Downloads

`scripts/gt-pull-direct.sh` writes incoming AFP files directly into
the requested local destination. It does not create a temporary
archive tree or perform a second copy.

Failed or truncated files are removed by the direct-download
integrity cleanup. Matching incomplete Netatalk `.AppleDouble`
sidecars are also removed.

## Shared afpsld daemon

AFP client commands for one Unix user share an `afpsld` daemon.

`gt-pull-direct.sh` must never terminate an existing daemon at
startup. Multiple client shells may therefore coexist without one
wrapper deliberately killing another transfer.

Concurrent native-ATP operation is still under validation and
should be treated as a testable capability rather than a guaranteed
performance feature until soak testing is complete.

## Resetting afpsld

Use:

    scripts/gt-afp-reset.sh

The reset helper refuses to terminate the daemon while AFP client
commands are active.

An intentional disruptive reset can be requested with:

    scripts/gt-afp-reset.sh --force

## ATP tracing

`GT_ATP_TRACE` is inherited by `afpsld` when that daemon starts.

For example:

    GT_ATP_TRACE=/tmp/gt-afp-shared.log \
        scripts/gt-pull-direct.sh ...

If another shell later reuses that already-running daemon, setting a
different `GT_ATP_TRACE` in the second shell does not change the
daemon's trace destination.

Therefore concurrent clients share one ATP trace for that daemon
lifetime. Use separate stdout/stderr logs for individual client
commands.
