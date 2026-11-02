# Backup sidecar.
#
# Based on the same PostgreSQL release as the `db` service, so pg_dump always
# matches the server it dumps. `age` is the only addition: when a recipient is
# configured the dump is piped through it before it touches the backup volume,
# and the recipient is a public key, so the host can create backups but cannot
# read them back. verify.sh proves a backup restores, status.sh reports on
# them; the Makefile's backup-* targets run them.
FROM postgres:17-alpine

RUN apk add --no-cache age

COPY backup.sh verify.sh status.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/verify.sh /usr/local/bin/status.sh

ENTRYPOINT ["/usr/local/bin/backup.sh"]
