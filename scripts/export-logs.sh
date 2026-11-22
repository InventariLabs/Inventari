#!/usr/bin/env bash
# Copy each day of the host journal to ./logs, encrypted for the offsite copy.
#
# The production stack sends every container to journald
# (docker-compose.prod.yml), so a container recreated by a deploy no longer
# takes its lines with it; how long the journal itself is kept and how much
# disk it may take is a host setting (DEPLOYMENT.md, "Keeping the server's
# logs"). This script is the copy that leaves the host: one file per day,
# gzipped and encrypted with the backup key, in
# logs/journal-<YYYY-MM-DD>.log.gz.age, pruned after LOG_RETENTION_DAYS.
# db-backup-offsite sends the *.age files to the offsite bucket, whose Object
# Lock keeps them for the same period where the destination has it.
#
# Run it once a day as root, from the checkout, with the environment of .env:
#
#   17 4 * * * cd /opt/inventari && set -a && . ./.env && set +a && ./scripts/export-logs.sh
#
# The whole journal is exported, not only the containers' lines: sshd and the
# rest of the host log are the evidence a break-in leaves, and whoever gets
# root has to erase the copy on the server only — this one is already off it.
#
# Usage: scripts/export-logs.sh [days]
#   days  how many past days to fill in (default: LOG_RETENTION_DAYS). A day
#         that already has a file is skipped, so a daily run writes yesterday
#         and leaves the rest alone, while the first run backfills what the
#         journal still holds. Nothing is written for a day the journal has no
#         entries for.
set -euo pipefail
cd "$(dirname "$0")/.."

log_dir="${LOG_DIR:-logs}"
keep="${LOG_RETENTION_DAYS:-30}"
recipient="${AGE_RECIPIENT:-}"
days="${1:-$keep}"

case "$keep" in
    '' | *[!0-9]*) echo "LOG_RETENTION_DAYS must be a whole number, got: $keep" >&2; exit 2 ;;
esac
case "$days" in
    '' | *[!0-9]*) echo "days must be a whole number, got: $days" >&2; exit 2 ;;
esac
if [ "$keep" -lt 1 ]; then
    echo "LOG_RETENTION_DAYS must be at least 1, got: $keep" >&2
    exit 2
fi
if [ -z "$recipient" ]; then
    echo "AGE_RECIPIENT is empty — the journal holds visitors' network addresses, so it leaves the host only encrypted. Run 'make backup-key' (see DEPLOYMENT.md)." >&2
    exit 1
fi
# A window wider than the retention would be pruned by the same run.
[ "$days" -le "$keep" ] || days="$keep"
for tool in journalctl gzip age date expr; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required" >&2; exit 1; }
done

# The journal belongs to root: the files are root-owned and the exports are
# readable by root only.
umask 077
mkdir -p "$log_dir"

# A day is written to temp files first and moved into place only once age has
# sealed it. A run that dies on the way leaves no plaintext and no half-made
# archive behind; the `find` at the end catches what a kill -9 leaves.
plain=""
sealed=""
cleanup() {
    [ -z "$plain" ] || rm -f "$plain"
    [ -z "$sealed" ] || rm -f "$sealed"
}
trap cleanup EXIT

# The journal is dated and queried in UTC throughout: the files are named by
# the UTC day they hold, and a server moved between time zones does not leave
# a gap or a doubled day.
i="$days"
while [ "$i" -ge 1 ]; do
    day="$(date -u -d "$i days ago" +%Y-%m-%d)"
    file="$log_dir/journal-$day.log.gz.age"
    if [ ! -f "$file" ]; then
        start="$(date -u -d "$day 00:00:00" +%s)"
        end="$(date -u -d "$day 00:00:00 + 1 day" +%s)"
        plain="$log_dir/.journal-$day.log.part"
        sealed="$file.part"
        # The journal is written to a root-only temp file first, so a day with
        # no entries leaves no empty archive and a journalctl that fails does
        # not read as one.
        journalctl --utc --no-pager -q -o short-iso \
            --since "@$start" --until "@$end" > "$plain"
        if [ -s "$plain" ]; then
            gzip -c "$plain" | age --encrypt --recipient "$recipient" --output "$sealed"
            mv -f "$sealed" "$file"
            sealed=""
        fi
        rm -f "$plain"
        plain=""
    fi
    i=$((i - 1))
done

# Keep exactly LOG_RETENTION_DAYS days of files. The name carries the day each
# one holds, so the comparison is by that day, not by when a backfill wrote it.
oldest="$(date -u -d "$keep days ago" +%Y-%m-%d)"
for file in "$log_dir"/journal-*.log.gz.age; do
    [ -f "$file" ] || continue
    stem="${file##*/}"
    day="${stem#journal-}"
    day="${day%.log.gz.age}"
    case "$day" in
        ????-??-??) ;;
        *) continue ;;
    esac
    if expr "$day" \< "$oldest" >/dev/null; then
        rm -f "$file"
    fi
done

# A run that died between the journal and age leaves a temp file that no
# filter or prune of the finished files ever touches.
find "$log_dir" -maxdepth 1 -type f -name '*.part' -mmin +60 -delete
