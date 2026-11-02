#!/bin/sh
# What the backups are: whether they are encrypted, when the newest dump and
# the newest archive of the uploaded files were written, and when a restore
# was last proven.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"

if [ -n "${AGE_RECIPIENT:-}" ]; then
    echo "encryption:     on — new backups are readable only with the private key"
else
    echo "encryption:     OFF — new backups are plain files (make backup-key turns it on)"
fi

# newest <kind>: the newest backup of a kind (sql.gz or tar.gz) in last/.
newest() {
    find "$BACKUP_DIR/last" -maxdepth 1 -type f \
        \( -name "*.$1" -o -name "*.$1.age" \) 2>/dev/null | sort | tail -n 1
}
hours_old() { echo $(( ($(date +%s) - $(stat -c %Y "$1")) / 3600 )); }

dump="$(newest sql.gz)"
if [ -n "$dump" ]; then
    echo "newest backup:  $(basename "$dump"), $(hours_old "$dump") h old"
else
    echo "newest backup:  none yet"
fi

files="$(newest tar.gz)"
if [ -n "$files" ]; then
    echo "newest files:   $(basename "$files"), $(hours_old "$files") h old"
else
    echo "newest files:   none — the uploaded photographs and attachments are in no backup"
fi

if [ -s "$BACKUP_DIR/last-verified" ]; then
    IFS="$(printf '\t')" read -r when what mode files_checked < "$BACKUP_DIR/last-verified"
    note=""
    if [ -n "${AGE_RECIPIENT:-}" ] && [ "$mode" = "plain" ]; then
        note=" — that was before encryption was on; verify again with the key"
    fi
    echo "restore check:  $when ($what, $mode)$note"
    if [ -n "${files_checked:-}" ]; then
        echo "files check:    $files_checked read back at $when"
    else
        echo "files check:    never — run: make backup-verify"
    fi
else
    echo "restore check:  never — run: make backup-verify"
    echo "files check:    never — run: make backup-verify"
fi
