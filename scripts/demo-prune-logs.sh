#!/bin/sh
# Drop the lines older than N days from the Docker logs of the demo stack.
#
# Docker's json-file driver can cap a log by size but not by age, and the
# server's logs carry visitors' network addresses (docs/DEMO.md, "Logs"). Run
# this once a day on the host, as root — the logs belong to the Docker daemon:
#
#     17 4 * * *  /path/to/inventari/scripts/demo-prune-logs.sh
#
#   scripts/demo-prune-logs.sh [days] [log file ...]
#
# `days` defaults to 7. With no file it reads the logs of every container of
# the compose project INVENTARI_DEMO_PROJECT (default `inventari-demo`) and the
# rotated files beside them; with files it prunes exactly those, which is how
# the test drives it.
#
# The daemon appends to the active log with no lock a reader could take, so a
# file rewritten while its container runs loses whatever the daemon writes
# between the read and the write back. The containers whose logs are read from
# Docker are therefore stopped for the rewrite and started again after it (a
# few seconds, at a quiet hour); files named on the command line are pruned as
# they are, and the caller answers for them being idle.
#
# The one exception is the demo-reset service: it rebuilds the whole demo every
# time it starts, so a stop and a start would wipe the visitors' data a second
# time after the nightly reset. It is paused instead (no process runs, nothing
# restarts) and resumed after the rewrite.
set -eu

days="${1:-7}"
[ "$#" -gt 0 ] && shift
project="${INVENTARI_DEMO_PROJECT:-inventari-demo}"

case "$days" in
    '' | *[!0-9]*) echo "days must be a whole number, got: $days" >&2; exit 2 ;;
esac

# The daemon stamps every line with an RFC 3339 UTC time, so the first 19
# characters of it sort as text exactly as they do as a clock.
cutoff="$(date -u -d "$days days ago" +%Y-%m-%dT%H:%M:%S)"

tmp="$(mktemp)"
# Whatever happens below, the containers that were running come back up.
trap 'rm -f "$tmp"
      [ -z "${frozen:-}" ] || docker unpause $frozen >/dev/null
      [ -z "${running:-}" ] || docker start $running >/dev/null' EXIT

if [ "$#" -eq 0 ]; then
    command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
    ids="$(docker ps -aq --filter "label=com.docker.compose.project=$project")"
    [ -n "$ids" ] || { echo "no container belongs to the project $project" >&2; exit 1; }
    running="$(docker ps -q --filter "label=com.docker.compose.project=$project")"
    reset="$(docker ps -q --filter "label=com.docker.compose.project=$project" \
        --filter "label=com.docker.compose.service=demo-reset")"
    # Everything running but the reset service is stopped; the reset service is
    # frozen, then given a second to hand the daemon what it had already written.
    for id in $reset; do running="$(printf '%s\n' "$running" | grep -vxF "$id" || true)"; done
    [ -z "$running" ] || docker stop $running >/dev/null
    if [ -n "$reset" ]; then
        docker pause $reset >/dev/null
        frozen="$reset"
        sleep 1
    fi
    # Listed only once nothing writes: a daemon that rotates a log between the
    # listing and the stop would leave the new rotated file out of the run.
    for id in $ids; do
        path="$(docker inspect -f '{{.LogPath}}' "$id")"
        [ -n "$path" ] || continue
        for file in "$path" "$path".*; do
            [ -f "$file" ] && set -- "$@" "$file"
        done
    done
fi

for file in "$@"; do
    # A line with no readable time cannot be dated, so it stays.
    awk -v cutoff="$cutoff" '
        match($0, /"time":"[^"]*"/) {
            if (substr($0, RSTART + 8, 19) < cutoff) next
        }
        { print }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
done
