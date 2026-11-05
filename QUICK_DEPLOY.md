# Quick Deploy — Inventari

Deploy to a VPS with automatic HTTPS in 6 steps.

## Requirements

- VPS with Ubuntu 26.04 LTS or Debian 13. The steps below are tested on
  Ubuntu 26.04 LTS, and Debian 13 takes the same commands. Another current
  64-bit Linux with Docker Engine and Docker Compose v2 should work too, but
  may need small adjustments (on Fedora or RHEL, for example, SELinux can
  refuse the containers access to the files mounted from the host).
- A domain name with an A record pointing to your VPS IP

---

## Step 1: Install Docker

```bash
ssh user@your-vps-ip
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # the script also installs Docker Compose v2
exit  # log out and back in to apply group changes
```

## Step 2: Clone a release

```bash
ssh user@your-vps-ip
sudo mkdir -p /opt/inventari && sudo chown $USER:$USER /opt/inventari
cd /opt/inventari
git clone https://github.com/InventariLabs/Inventari.git .
git tag --list 'v*' --sort=-v:refname | head -3   # the releases, newest first
git checkout v0.11.0                                # the one you install
```

A fresh clone stands on `dev`, where work in progress meets; a tag is a
release. *Updating* in [DEPLOYMENT.md](DEPLOYMENT.md) moves from one tag to
the next.

## Step 3: Configure

```bash
cp .env.production.example .env
nano .env
```

The copied file is the list of variables the stack reads. Seven have no
working default: five are hex-string secrets to generate (two of them,
`DB_APP_PASSWORD` and `REDIS_PASSWORD`, are interpolated into connection URLs
verbatim, where base64's `+ / =` characters would corrupt them; hex is the safe
choice for all five), plus the domain and the e-mail address for the
certificate. `docker compose` itself refuses to start without three of them
(`REDIS_PASSWORD`, `DB_APP_PASSWORD`, `FERNET_SALT`) and says which; left
empty, the other four fail later and less clearly — the database will not
initialise without `DB_PASSWORD`, the backend will not boot without a
`SECRET_KEY` of at least 32 bytes, and Caddy cannot obtain a certificate
without `DOMAIN` and `ACME_EMAIL`:

```env
DOMAIN=inventari.example.com
ACME_EMAIL=you@example.com
DB_PASSWORD=     # use: openssl rand -hex 32
DB_APP_PASSWORD= # use: openssl rand -hex 32
REDIS_PASSWORD=  # use: openssl rand -hex 32
SECRET_KEY=      # use: openssl rand -hex 32
FERNET_SALT=     # use: openssl rand -hex 32
```

Set `ENCRYPTION_KEY` the same way (`openssl rand -hex 32`). It is optional,
but without it `SECRET_KEY` also encrypts the secrets organizations store, and
rotating it means re-encrypting them all (*Rotating the encryption key* in
[DEPLOYMENT.md](DEPLOYMENT.md)). Never change `FERNET_SALT` once a secret is
saved: there is no way back from that.

Optionally add `WWW_DOMAIN=www.inventari.example.com` to make that name
redirect to the main address. It needs its own DNS record (A to the same
address, or CNAME to `DOMAIN`) first; leave it empty otherwise.

`DB_PASSWORD` belongs to the database's administrator role; the application
connects with `DB_APP_PASSWORD`, as a role without superuser rights (see
*Database roles* in [DEPLOYMENT.md](DEPLOYMENT.md)).

**Keep a copy of the finished `.env` off the server**, in your password
manager. No backup contains it, and a database restored without its
`ENCRYPTION_KEY` (or `SECRET_KEY`) and `FERNET_SALT` cannot read the secrets organizations stored in
it (*Rebuilding on a new server* in [DEPLOYMENT.md](DEPLOYMENT.md)).

**Backups run from the first night, with no key to set up** — the database and
the uploaded photographs and attachments. Left alone they are plain files only
root can read, and the log says so at every run. Encrypting
them is your choice — `make backup-key` prints a key pair, and the private half
must then be kept off the server, because without it the backups cannot be read
by anyone. It is explained, with `make backup-verify` to prove a backup
restores, in *Database Backups* in [DEPLOYMENT.md](DEPLOYMENT.md); you can do it
today or after the stack is up.

`DB_APP_PASSWORD`, `REDIS_PASSWORD` and `FERNET_SALT` are
enforced by the compose file itself — an empty value stops
`docker compose up` with a `required variable … is missing` error, before
anything is built.

The remaining empty fields in the example are optional; the ones most
installations meet are:

- `AGE_RECIPIENT` — the public key that encrypts backups; see above.
- `PRODUCTS_DB_PASSWORD` and `PRODUCTS_DB_APP_PASSWORD` — only used by the
  optional Open Food Facts database; see *Optional: the Open Food Facts
  database* in [DEPLOYMENT.md](DEPLOYMENT.md). Both are required once the
  `food` profile is on: the second one is refused empty by `products-app-role`,
  the one-shot that gives the products database its non-superuser role.
- `LLM_API_KEY` — enables Vision AI: the API key of the AI provider chosen by
  `LLM_PROVIDER` (OpenRouter unless set otherwise).
- `OPERATOR_NAME` and `OPERATOR_CONTACT` — who runs the instance and how people
  reach you about their data, shown on the public privacy page; fill them in
  before the instance goes public.
- `SOURCE_CODE_URL` — leave empty unless you run a modified version; then
  AGPL-3.0 §13 requires it to point at your own source.

The comment above each variable in the file says what it does.

## Step 4: Deploy — everything but the proxy

```bash
docker compose -f docker-compose.prod.yml up -d --build --scale caddy=0
until docker compose -f docker-compose.prod.yml exec -T backend \
    curl -sf http://localhost:8000/health/ready >/dev/null; do sleep 5; done
```

The first command builds and starts every service except Caddy, the proxy
that puts the installation on the internet; the second returns once the
backend has migrated the database and answers. Nothing outside the server
can reach it yet.

## Step 5: Create the administrator — before the proxy starts

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py user create-admin \
    --email you@example.com --password '<your password>' --name "Your Name"
```

Replace all three placeholders. The password needs at least 8 characters, with a
lowercase letter, an uppercase letter and a digit — the command refuses
anything less. Typed this way it lands in the shell's history; a leading space
keeps it out where `HISTCONTROL` includes `ignorespace` (Ubuntu's default).

The first account is the installation's administrator and superuser. From
now on registration is closed to strangers — everyone else needs an
invitation, or a request for access that an administrator approves. Caddy waits until this step on purpose: once it starts, it
requests a certificate, and every certificate is published in public logs
that scanners watch for new names, often within minutes. An installation
with no account belongs to whoever registers there first; created now, the
administrator exists before anyone can.

## Step 6: Start the proxy and sign in

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f caddy
```

Without `--scale`, `up -d` starts Caddy and leaves the services already
running as they are. Wait 1–2 minutes for Let's Encrypt to issue the
certificate. Then open `https://inventari.example.com`, sign in, choose the
workspace, and name the organization (it starts as "My Organization") in
**Settings → General**. Mail — invitations, purchase orders, notifications —
goes through the SMTP server you set in **Settings → Email**; without it an
invitation is still created, and you pass its link on yourself.

---

## Updating

Updates start with a backup — the only way back if the update fails. Take one
before anything else is touched:

```bash
cd /opt/inventari
docker compose -f docker-compose.prod.yml run --rm -e BACKUP_ONCE=true db-backup
sudo cp -a backups/last backups/before-update
```

Everything after it — the release's section in the changelog, the next tag,
the variables the example gained, the build, the recreate and the migrations
— is *Updating* in [DEPLOYMENT.md](DEPLOYMENT.md#updating), step by step, and
*When an update fails* in the same guide goes back to the tag you came from
with the backup above put back. Backups also run on their own from the first
night (*Database Backups* in the same guide); this one is taken by hand
because an update is what it is for.

---

## Troubleshooting

**SSL certificate not issued?**
```bash
ping inventari.example.com           # check DNS
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
docker compose -f docker-compose.prod.yml logs caddy
```

**Locked out — the administrator forgot the password?** Without outgoing mail
there is no reset link; reset it from the server with the command that created
the account. It sets the new password, keeps the administrator role and signs
out every earlier session:
```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py user create-admin \
    --email you@example.com --password '<a new password>'
```

**Backend not starting?**
```bash
docker compose -f docker-compose.prod.yml logs backend
docker compose -f docker-compose.prod.yml restart
```

---

Full documentation: **[DEPLOYMENT.md](DEPLOYMENT.md)**
