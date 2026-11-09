#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
    echo 'Refusing to run Ownfoil as root; configure Docker user UID:GID.' >&2
    exit 1
fi
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    echo 'PUID/PGID are no longer supported; configure Docker user UID:GID.' >&2
    exit 1
fi
for directory in /app/config /app/data; do
    if [ ! -w "$directory" ]; then
        echo "$directory must be writable by the configured container user." >&2
        exit 1
    fi
done
exec python /app/run.py
