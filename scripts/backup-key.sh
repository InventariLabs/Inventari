#!/bin/sh
# make backup-key — generate the key pair that encrypts the production backups.
#
# The private key is printed once and written nowhere: it never touches this
# disk, which is the point of it. Without it an encrypted backup cannot be
# read by anyone, so the message says that before the key scrolls past, and
# `make backup-verify` is how you prove the copy you kept works.
set -eu

command -v docker >/dev/null 2>&1 || {
    echo "docker is required: the key is made with the age in the backup image." >&2
    exit 1
}

here="$(cd "$(dirname "$0")/.." && pwd)"
image="inventari-backup-tool:local"
docker build -q -t "$image" "$here/docker/backup" >/dev/null

key="$(docker run --rm --entrypoint age-keygen "$image" 2>/dev/null)"
public="$(printf '%s\n' "$key" | sed -n 's/^# public key: //p')"
[ -n "$public" ] || { echo "age-keygen gave no public key" >&2; exit 1; }

cat <<MSG

  BACKUP KEY — read this before anything else
  ───────────────────────────────────────────
  Below is the PRIVATE key. It is shown once and saved nowhere.

  Without it the encrypted backups cannot be read — not by you, not by us,
  not by anyone. A backup you cannot read is worth nothing.

  Save it NOW, somewhere that is not this server: a password manager is
  right. Do not leave it on the server — the point is that the server can
  write backups but cannot read them.

$key

  Next:
    1. Put this line in .env:     AGE_RECIPIENT=$public
    2. Recreate the backup job:   docker compose -f docker-compose.prod.yml up -d db-backup
    3. After its first backup, prove the key works (the key goes in on
       stdin and is not written to the server):
         ssh you@your-vps 'cd /opt/inventari && make backup-verify' < backup-key.txt
       or on the server itself:   make backup-verify    (paste the key, Ctrl-D)

MSG
