#!/bin/sh
# Rotating backups of the PostgreSQL database and of the uploaded files,
# encrypted when a key is given.
#
# With AGE_RECIPIENT set, the dump is piped through gzip and age before it
# touches the disk, so the backup volume only ever holds ciphertext.
# AGE_RECIPIENT is an age PUBLIC key: this host can create backups but cannot
# read them back. Restoring needs the matching private key and is documented
# in DEPLOYMENT.md ("Database Backups") — including the procedure that was
# actually run.
#
# With AGE_RECIPIENT empty the stack still backs up — a backup nobody asked
# to encrypt beats none, and a key made only to get past a startup check is
# one nobody has kept. The dump is then plain gzip (<db>-<timestamp>.sql.gz,
# readable by root only), and every run says so in the log.
#
# The uploaded files — photographs, attachments — live in a volume of their
# own (UPLOADS_DIR, mounted read-only), and a database restored without them
# points at pictures that are gone. So every run also archives that volume
# into uploads-<timestamp>.tar.gz[.age], under the same key or the same
# root-only mode as the dump. A volume that cannot be read fails the run after
# the dump is written: the database backup stands, and the restart says the
# files are missing.
#
# Files land in <db>-<timestamp>.sql.gz[.age] and
# uploads-<timestamp>.tar.gz[.age] under last/, and are hard-linked to daily/,
# weekly/ and monthly/ (copied when the filesystem refuses hard links, e.g. an
# SMB mount). Retention: BACKUP_KEEP_DAYS daily, _WEEKS weekly, _MONTHS
# monthly. Every archive is a full copy of the files, so the backup volume
# needs room for that many copies of them. One run happens at container start,
# then once a day at BACKUP_HOUR (UTC).
#
# BACKUP_ONCE=true runs a single backup and exits — for a manual run:
#   docker compose -f docker-compose.prod.yml run --rm -e BACKUP_ONCE=true db-backup
set -eu
set -o pipefail

log() { printf '%s [db-backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

: "${POSTGRES_HOST:?required}"
: "${POSTGRES_DB:?required}"
: "${POSTGRES_USER:?required}"
: "${POSTGRES_PASSWORD:?required}"

AGE_RECIPIENT="${AGE_RECIPIENT:-}"
if [ -n "$AGE_RECIPIENT" ]; then
    EXT="sql.gz.age"
    FILES_EXT="tar.gz.age"
else
    EXT="sql.gz"
    FILES_EXT="tar.gz"
fi

BACKUP_DIR="${BACKUP_DIR:-/backups}"
UPLOADS_DIR="${UPLOADS_DIR:-/uploads}"
BACKUP_HOUR="${BACKUP_HOUR:-2}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
KEEP_WEEKS="${BACKUP_KEEP_WEEKS:-4}"
KEEP_MONTHS="${BACKUP_KEEP_MONTHS:-6}"

export PGPASSWORD="$POSTGRES_PASSWORD"

link_or_copy() {
    ln -f "$1" "$2" 2>/dev/null || cp -f "$1" "$2"
}

rotate() {
    # Both extensions of both kinds: a stack that gained or lost its key keeps
    # rotating the backups it made the other way.
    find "$BACKUP_DIR/daily" -maxdepth 1 -type f \
        \( -name '*.sql.gz' -o -name '*.sql.gz.age' -o -name '*.tar.gz' -o -name '*.tar.gz.age' \) \
        -mtime "+$KEEP_DAYS" -delete
    find "$BACKUP_DIR/weekly" -maxdepth 1 -type f \
        \( -name '*.sql.gz' -o -name '*.sql.gz.age' -o -name '*.tar.gz' -o -name '*.tar.gz.age' \) \
        -mtime "+$((KEEP_WEEKS * 7 + 1))" -delete
    find "$BACKUP_DIR/monthly" -maxdepth 1 -type f \
        \( -name '*.sql.gz' -o -name '*.sql.gz.age' -o -name '*.tar.gz' -o -name '*.tar.gz.age' \) \
        -mtime "+$((KEEP_MONTHS * 31 + 1))" -delete
    # Leftovers of an interrupted run; the name never survives a successful
    # one, so anything this old means the process died mid-dump.
    find "$BACKUP_DIR/last" -maxdepth 1 -type f -name '*.part' -mmin +60 -delete
}

# publish <name> <kind> <ext> <file>: last/<file>.part becomes the newest
# backup of its kind (sql.gz or tar.gz) — renamed into place, <name>-latest
# pointed at it, the previous one in last/ (made with or without a key)
# removed, and linked into the daily, weekly and monthly folders.
publish() {
    local name="$1" kind="$2" ext="$3" file="$4"
    # Published only once the whole pipeline succeeded; .part is invisible
    # to the retention of the folders below and to a restore attempt.
    mv -f "$BACKUP_DIR/last/$file.part" "$BACKUP_DIR/last/$file"
    ln -sfn "$file" "$BACKUP_DIR/last/${name}-latest.${ext}"
    # Only the newest of the kind stays in last/ — whichever way it was made.
    find "$BACKUP_DIR/last" -maxdepth 1 -type f \
        \( -name "*.${kind}" -o -name "*.${kind}.age" \) ! -name "$file" -delete
    find "$BACKUP_DIR/last" -maxdepth 1 -type l -name "${name}-latest.*" \
        ! -name "${name}-latest.${ext}" -delete

    link_or_copy "$BACKUP_DIR/last/$file" "$BACKUP_DIR/daily/${name}-${day}.${ext}"
    link_or_copy "$BACKUP_DIR/last/$file" "$BACKUP_DIR/weekly/${name}-${week}.${ext}"
    link_or_copy "$BACKUP_DIR/last/$file" "$BACKUP_DIR/monthly/${name}-${month}.${ext}"
}

# seal <part>: stdin to <part>, through age when there is a key, readable by
# root only when there is not.
seal() {
    if [ -n "$AGE_RECIPIENT" ]; then
        age --encrypt --recipient "$AGE_RECIPIENT" --output "$1"
    else
        # umask: a plain backup is readable by root only, not by every user on the host.
        (umask 077 && cat > "$1")
    fi
}

archive_files() {
    files_base="uploads-${stamp}.${FILES_EXT}"
    part="$BACKUP_DIR/last/$files_base.part"
    if [ ! -d "$UPLOADS_DIR" ]; then
        log "files archive FAILED — ${UPLOADS_DIR} is not there, so the uploaded" \
            "photographs and attachments are NOT in this backup (the database dump stands)"
        return 1
    fi
    log "archiving the uploaded files in ${UPLOADS_DIR} to ${files_base}"
    if ! tar -C "$UPLOADS_DIR" -cf - . | gzip -6 | seal "$part"; then
        rm -f "$part"
        log "files archive FAILED — the uploaded photographs and attachments are" \
            "NOT in this backup (the database dump stands)"
        return 1
    fi
    publish uploads tar.gz "$FILES_EXT" "$files_base"
}

run_backup() {
    mkdir -p "$BACKUP_DIR/last" "$BACKUP_DIR/daily" \
             "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"

    stamp="$(date -u +%Y%m%d-%H%M%S)"
    day="$(date -u +%Y%m%d)"
    week="$(date -u +%G%V)"
    month="$(date -u +%Y%m)"
    base="${POSTGRES_DB}-${stamp}.${EXT}"
    part="$BACKUP_DIR/last/$base.part"

    if [ -n "$AGE_RECIPIENT" ]; then
        log "dumping ${POSTGRES_DB} from ${POSTGRES_HOST} and encrypting to ${base}"
    else
        log "WARNING: AGE_RECIPIENT is empty, so this backup is stored UNENCRYPTED" \
            "in ${BACKUP_DIR} — whoever can read that disk can read the database." \
            "To encrypt: run 'make backup-key', put its AGE_RECIPIENT line in .env" \
            "and recreate db-backup (DEPLOYMENT.md, \"Database Backups\")."
        log "dumping ${POSTGRES_DB} from ${POSTGRES_HOST} to ${base}"
    fi
    if ! pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        | gzip -9 | seal "$part"; then
        rm -f "$part"
        log "dump FAILED — no new backup was written"
        return 1
    fi
    publish "$POSTGRES_DB" sql.gz "$EXT" "$base"

    files_ok=true
    archive_files || files_ok=false
    rotate

    log "backup written: $base ($(wc -c < "$BACKUP_DIR/last/$base") bytes)"
    if [ "$files_ok" = true ]; then
        log "files written: $files_base ($(wc -c < "$BACKUP_DIR/last/$files_base") bytes)"
    else
        return 1
    fi
}

if [ "${BACKUP_ONCE:-false}" = "true" ]; then
    run_backup
    exit 0
fi

# A run at every start means a fresh container has a restore point straight
# away, and a failure exits so the restart policy makes it loud instead of
# waiting silently for the next night.
run_backup
while :; do
    now="$(date -u +%s)"
    target_at=$((BACKUP_HOUR * 3600))
    since_midnight=$((now % 86400))
    if [ "$since_midnight" -lt "$target_at" ]; then
        wait=$((target_at - since_midnight))
    else
        wait=$((86400 - since_midnight + target_at))
    fi
    log "next backup in ${wait}s"
    sleep "$wait"
    run_backup
done
