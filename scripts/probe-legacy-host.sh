#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Collect the information needed to build afpcmd on an older Netatalk host.
# This script is intentionally POSIX sh and does not require Meson.

set +e

section()
{
    echo
    echo "===== $* ====="
}

run()
{
    echo "+ $*"
    "$@" 2>&1
    echo "[rc=$?]"
}

section "System"
run uname -a
if [ -r /etc/os-release ]; then
    run cat /etc/os-release
fi
if [ -r /etc/debian_version ]; then
    run cat /etc/debian_version
fi
run python3 --version

section "Build tools"
for tool in cc gcc make pkg-config meson ninja ninja-build; do
    path=$(command -v "$tool" 2>/dev/null)
    if [ -n "$path" ]; then
        echo "$tool=$path"
        "$tool" --version 2>&1 | head -n 3
    else
        echo "$tool=NOT FOUND"
    fi
done

section "Netatalk / AppleTalk commands"
for tool in nbplkup nbp_name afpd atalkd; do
    path=$(command -v "$tool" 2>/dev/null)
    if [ -n "$path" ]; then
        echo "$tool=$path"
    else
        echo "$tool=NOT FOUND"
    fi
done

NBP=$(command -v nbplkup 2>/dev/null)
if [ -n "$NBP" ] && command -v ldd >/dev/null 2>&1; then
    echo
    echo "+ ldd $NBP"
    ldd "$NBP" 2>&1
fi

section "AppleTalk headers"
for root in /usr/include /usr/local/include /opt/local/include; do
    for hdr in atalk/atp.h atalk/asp.h atalk/nbp.h atalk/netddp.h; do
        if [ -r "$root/$hdr" ]; then
            echo "FOUND $root/$hdr"
        fi
    done
done

section "Library cache"
if command -v ldconfig >/dev/null 2>&1; then
    ldconfig -p 2>/dev/null | grep -E 'lib(atalk|readline|edit|gcrypt|bsd)' || true
else
    echo "ldconfig=NOT FOUND"
fi

section "Compiler header probes"
TMP=${TMPDIR:-/tmp}/gt-afp-probe-$$
mkdir -p "$TMP"

probe_header()
{
    hdr=$1
    printf '#include <%s>\nint main(void){return 0;}\n' "$hdr" > "$TMP/probe.c"
    echo "+ cc -c probe for <$hdr>"
    cc -c "$TMP/probe.c" -o "$TMP/probe.o" 2>&1
    echo "[rc=$?]"
}

probe_header atalk/atp.h
probe_header atalk/asp.h
probe_header atalk/nbp.h
probe_header readline/readline.h
probe_header editline/readline.h
probe_header sys/xattr.h

section "Compiler link probes"
printf 'int main(void){return 0;}\n' > "$TMP/probe.c"
for lib in atalk readline edit pthread gcrypt bsd; do
    echo "+ cc probe.c -l$lib"
    cc "$TMP/probe.c" -o "$TMP/probe" "-l$lib" 2>&1
    echo "[rc=$?]"
done

rm -rf "$TMP"

section "Installed package hints"
if command -v dpkg-query >/dev/null 2>&1; then
    dpkg-query -W 2>/dev/null | grep -Ei 'netatalk|readline|libedit|gcrypt|libbsd|meson|ninja' || true
elif command -v rpm >/dev/null 2>&1; then
    rpm -qa 2>/dev/null | grep -Ei 'netatalk|readline|libedit|gcrypt|libbsd|meson|ninja' || true
else
    echo "No dpkg-query or rpm package database found."
fi

echo
echo "===== Probe complete ====="
