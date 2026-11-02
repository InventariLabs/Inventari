#!/bin/sh
# Proves the newest backup restores.
#
# A backup nobody has restored is a hypothesis, and an encrypted one is worth
# nothing if the private key was lost or never matched. This loads the newest
# dump in last/ into a scratch database on the live server, checks that tables
# came back, drops the scratch database, then reads the newest archive of the
# uploaded files through to its last entry. Only when both came back is the
# time of the success recorded in <backups>/last-verified — which status.sh
# reads.
#
# An encrypted backup needs the PRIVATE key. It is read from stdin and never
# written anywhere, so it can be piped in over ssh without touching the host:
#   ssh you@your-vps 'cd /opt/inventari && make backup-verify' < backup-key.txt
# It is held in a shell variable for the two files that need it, and handed to
# age through a pipe from the shell's own printf — never as an argument a
# process listing would show.
set -eu
set -o pipefail

: "${POSTGRES_HOST:?required}"
: "${POSTGRES_DB:?required}"
: "${POSTGRES_USER:?required}"
: "${POSTGRES_PASSWORD:?required}"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
SCRATCH="${POSTGRES_DB}_verify"
export PGPASSWORD="$POSTGRES_PASSWORD"
# DROP DATABASE IF EXISTS announces the common case, a scratch database that is not there.
export PGOPTIONS="-c client_min_messages=warning"

say() { printf '%s\n' "$*"; }
fail() { printf 'backup-verify FAILED: %s\n' "$*" >&2; exit 1; }

psql_admin() { psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -v ON_ERROR_STOP=1 -q "$@"; }

# newest <kind>: the newest backup of a kind (sql.gz or tar.gz) in last/.
newest() {
    find "$BACKUP_DIR/last" -maxdepth 1 -type f \
        \( -name "*.$1" -o -name "*.$1.age" \) 2>/dev/null | sort | tail -n 1
}

dump="$(newest sql.gz)"
[ -n "$dump" ] || fail "there is no backup in $BACKUP_DIR/last yet"
files="$(newest tar.gz)"
[ -n "$files" ] || fail "the backup in $BACKUP_DIR/last holds no archive of the uploaded files — run a backup (DEPLOYMENT.md, \"Manual backup\") and verify again"
base="$(basename "$dump")"
files_base="$(basename "$files")"

key=""
case "$base $files_base" in
    *.age*)
        mode="encrypted"
        [ -t 0 ] && say "Paste the PRIVATE key (the AGE-SECRET-KEY-1… line), then press Ctrl-D:" >&2
        key="$(cat)"
        ;;
    *)
        mode="plain"
        ;;
esac

# reader <file>: the file as it was before age, gzip still on.
reader() {
    case "$1" in
        *.age) printf '%s\n' "$key" | age --decrypt -i - "$1" ;;
        *) cat "$1" ;;
    esac
}

psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" \
    -c "CREATE DATABASE \"$SCRATCH\"" || fail "could not create the scratch database"
trap 'psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" >/dev/null 2>&1 || true' EXIT

say "restoring $base ($mode) into a scratch database…"
reader "$dump" | gunzip | psql_admin -d "$SCRATCH" -o /dev/null \
    || fail "the backup did not decrypt or did not load — with an encrypted backup, check the key is the one whose public half is AGE_RECIPIENT"

tables="$(psql_admin -d "$SCRATCH" -t -A \
    -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
[ "${tables:-0}" -gt 0 ] || fail "the dump loaded but holds no tables"

say "reading $files_base through…"
count="$(reader "$files" | gunzip | tar -tf - | awk '!/\/$/ { n++ } END { print n + 0 }')" \
    || fail "the archive of the uploaded files did not decrypt or does not read — $files_base"

printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$base" "$mode" "$files_base" \
    > "$BACKUP_DIR/last-verified"
noun="files"
[ "$count" = 1 ] && noun="file"
say "OK — $base restored into a scratch database with $tables tables;" \
    "$files_base holds $count $noun."
