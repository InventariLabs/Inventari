# Quick Deploy — Inventari

Inventari on a server with a domain, with HTTPS from Let's Encrypt, in one
command. A computer at home with no domain is
[docs/HOME_INSTALL.md](docs/HOME_INSTALL.md).

The documentation is also readable on the website, in six languages:
[inventari.app/docs](https://inventari.app/docs/).

## Install

Log in to the server and run:

```bash
curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- vps
```

It asks four things: the domain, the e-mail address Let's Encrypt writes to
about the certificate, and the administrator's e-mail address and password —
8 characters or more, with a lowercase letter, an uppercase letter and a
digit. Then it works on its own for a few minutes, and ends with the address:

```text
Inventari 0.14.0 is running at

    https://inventari.example.com
```

Open it, sign in as the administrator, and the first screens ask what the
installation is for and what the organization is called.

What the server needs:

- Linux, 64-bit (amd64 or arm64), with 4 GB of memory or more. Ubuntu 26.04
  LTS and Debian 13 are the ones tested; macOS and Windows are not.
- A domain name whose A record points at the server's address. The command
  stops at once if the name does not resolve yet.
- Ports 80 and 443 free, and open in the provider's firewall.
- Root, or an account that may use `sudo`.

## What it did

- Installed Docker, and git, where they were missing.
- Fetched the release into `/opt/inventari`: a git checkout of its tag, which
  is what an update later moves to the next one.
- Wrote `/opt/inventari/.env` with `scripts/init-env.sh`: the domain, the
  e-mail address and six generated secrets, readable by its owner only, plus
  a line naming the release's published images, so every later
  `docker compose` command runs there as it is written below.
- Downloaded those images and started everything except Caddy, the proxy
  that puts the installation on the internet.
- Created the administrator, and only then started Caddy. Caddy's request
  for a certificate is published in public logs that scanners watch for new
  names, often within minutes, and an installation with no account belongs
  to whoever registers there first — this order leaves no such moment.
- Waited until the address answered over HTTPS.

Run the same line again and it changes nothing and says so. When a step
fails, it says which one and what to check; run the line again once that is
fixed, and it continues from that step.

## Keep these in mind

**Keep a copy of `/opt/inventari/.env` off the server**, in your password
manager. No backup contains it, and a database restored without its
`ENCRYPTION_KEY` and `FERNET_SALT` cannot read the secrets organizations
stored in it (*Rebuilding on a new server* in [DEPLOYMENT.md](DEPLOYMENT.md)).

**Backups run from the first night, with no key to set up** — the database
and the uploaded photographs and attachments, as plain files only root can
read, and the log says so at every run. Encrypting them is your choice:
*Database Backups* in [DEPLOYMENT.md](DEPLOYMENT.md#database-backups)
explains the key pair and how to prove a backup restores.

**Mail** — invitations, purchase orders, notifications — goes through the
SMTP server you set in **Settings → Email**; without one an invitation is
still created, and you pass its link on yourself.

**Before the instance goes public**, fill in `OPERATOR_NAME` and
`OPERATOR_CONTACT` in `.env`, which the public privacy page shows. The comment
above each variable in `.env` says what it does; *Step 4* of
[DEPLOYMENT.md](DEPLOYMENT.md) goes through the ones most installations meet,
and *Sizing the services to the host* the memory settings.

Later commands run in `/opt/inventari`. When the installer added your account
to the `docker` group, log out and back in once before using them; until then,
put `sudo` in front.

---

## Updating

Updates start with a backup — the only way back if the update fails. Take one
before anything else is touched:

```bash
cd /opt/inventari
docker compose run --rm -e BACKUP_ONCE=true db-backup
sudo cp -a backups/last backups/before-update
```

Everything after it — the release's section in the changelog, the next tag,
the variables the example gained, the new images, the recreate and the
migrations — is *Updating* in [DEPLOYMENT.md](DEPLOYMENT.md#updating), step by
step, with the changes its *Pulling the published images* paragraph names, and
*When an update fails* in the same guide goes back to the tag you came from
with the backup above put back.

---

## Troubleshooting

**The command stopped?** The last lines say which step failed and what to
check. Fix that and run the same line again: what is done stays as it is.

**The certificate is not issued?**
```bash
getent hosts inventari.example.com   # the address the name points at
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
cd /opt/inventari && docker compose logs caddy
```

**Locked out — the administrator forgot the password?** Without outgoing mail
there is no reset link; reset it from the server with the command that
creates the account. It sets the new password, keeps the administrator role
and signs out every earlier session:
```bash
cd /opt/inventari
docker compose exec backend python manage.py user create-admin \
  --email you@example.com --password '<a new password>'
```

**Backend not starting?**
```bash
cd /opt/inventari
docker compose logs backend
docker compose restart
```

---

The same installation by hand, step by step, the build from source and
everything else: **[DEPLOYMENT.md](DEPLOYMENT.md)**.
