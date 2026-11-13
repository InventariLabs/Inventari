# Deployment Guide

This guide covers deploying Inventari on a VPS with automatic HTTPS via **Caddy**.

## Prerequisites

- VPS with Ubuntu 26.04 LTS or Debian 13. The steps below are tested on
  Ubuntu 26.04 LTS, and Debian 13 takes the same commands. Another current
  64-bit Linux with Docker Engine and Docker Compose v2.20 or newer (the
  compose file uses `depends_on` with `required: false`) should work too, but
  may need small adjustments (on Fedora or RHEL, for example, SELinux can
  refuse the containers access to the files mounted from the host).
- A domain name with an A record pointing to your VPS IP
- Root or sudo access

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
git checkout v0.12.0                                # the one you install
```

A fresh clone stands on `dev`, the branch where work in progress meets — not
a release. Checking out a tag gives the installation a version with a name:
*Updating* below moves it from one tag to the next, a failed update goes back
to the previous one, and `git describe --tags` always says which one the
server runs. Git reports the checkout as a "detached HEAD"; that is expected.

## Step 3: Configure DNS

In your domain registrar's control panel, create an A record:

```
inventari.example.com → your.vps.ip.address
```

If visitors may also type `www.`, create a second record for it (an A record
to the same address, or a CNAME to `inventari.example.com`) and set
`WWW_DOMAIN=www.inventari.example.com` in `.env` in the next step. Caddy then
gets a certificate for that name and redirects it permanently to the main
address. Without the record, leave `WWW_DOMAIN` empty: Caddy would otherwise
try, and fail, to validate a name that does not resolve to the server.

Verify propagation (usually a few minutes):

```bash
ping inventari.example.com
```

## Step 4: Configure Environment

```bash
cp .env.production.example .env
nano .env
```

Generate secure secrets:

```bash
echo "DB_PASSWORD=$(openssl rand -hex 32)"
echo "DB_APP_PASSWORD=$(openssl rand -hex 32)"
echo "REDIS_PASSWORD=$(openssl rand -hex 32)"
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)"
echo "FERNET_SALT=$(openssl rand -hex 32)"
```

`DB_APP_PASSWORD` and `REDIS_PASSWORD` are interpolated into connection URLs
verbatim, so they must be hex — base64's `+ / =` characters would corrupt the
URLs rather than fail loudly. Hex is right for the other four as well.

`SECRET_KEY` signs login tokens; `ENCRYPTION_KEY` encrypts what organizations
store as secrets. Set both now, on the first install. `ENCRYPTION_KEY` may be
left empty — `SECRET_KEY` then does both jobs, as every install did before it
existed — but then rotating `SECRET_KEY` after a suspected token leak, which
otherwise only logs everyone out, also means re-encrypting every stored secret
(*Rotating the encryption key* below).

**Never change `FERNET_SALT` after the first secret is saved.** It salts every
key derived from `ENCRYPTION_KEY` (or `SECRET_KEY`), nothing can rotate it, and
a changed salt leaves every stored secret unreadable for good — they can only
be typed in again. A key has a rotation path; the salt does not.

**On a machine that also runs a development checkout,** give the installation
its own Compose project name. `docker-compose.prod.yml` pins the project name
`inventari`, which is also the name a development checkout gets by default, so
every `docker compose -f docker-compose.prod.yml …` command in this guide would
act on the development stack's containers and volumes. Add a line such as
`COMPOSE_PROJECT_NAME=inventari-prod` to the new `.env` before Step 5 and keep
it there: Compose reads it for every later command, and the volumes are named
after it. A server that runs only the installation needs nothing.

**Keep a copy of the finished `.env` off the server** — in the password
manager, next to any other key you keep. No backup contains it, and two of its
values cannot be made again: `ENCRYPTION_KEY` (or `SECRET_KEY`, if you leave
it empty) and `FERNET_SALT` derive the key that
encrypts what organizations store as secrets (AI provider keys, mail
passwords). A database restored under different values opens, but those
secrets in it can no longer be read. *Rebuilding on a new server* below starts
from this copy; refresh it whenever you change `.env`.

Database backups need no key to start: leave `AGE_RECIPIENT` empty and the
stack backs up anyway, to plain files only root can read, with a warning in the
log at every run. Encrypting them is a choice you can make now or later — and
it is a choice with a catch, so read "Database Backups" below first. In short:
the key is generated as a pair, `make backup-key` prints the private half once
and saves it nowhere, and that half must be kept off the server, because an
encrypted backup nobody can decrypt is worth less than a plain one.

Set at minimum in `.env`:

```env
DOMAIN=inventari.example.com
ACME_EMAIL=you@example.com
DB_PASSWORD=<generated above>
DB_APP_PASSWORD=<generated above>
REDIS_PASSWORD=<generated above>
SECRET_KEY=<generated above>
ENCRYPTION_KEY=<generated above>
FERNET_SALT=<generated above>
```

`DB_APP_PASSWORD`, `REDIS_PASSWORD` and `FERNET_SALT` are enforced by the
compose file — an empty value stops `docker compose up` before anything is
built. With these eight the finished stack runs nine services, Caddy
included (eight until Step 6 starts the proxy), and one of them
(`db-app-role`) runs once at every start and exits. The remaining empty
fields in the example are optional; the next section covers the Open Food
Facts database.

Before the instance goes public, fill in two more: `OPERATOR_NAME` and
`OPERATOR_CONTACT` — who runs it and how people reach you about their data.
The public privacy page (`/privacy`) shows them and tells visitors to ask you
for a copy of their data or its deletion; left empty, it says the operator
has published no contact. If you run a modified version, also point
`SOURCE_CODE_URL` at your own source: AGPL-3.0 §13 requires it, and the About
screen links it.

`DEFAULT_LANGUAGE` (`en` unless set; `pl`, `de`, `fr` or `es`) is the language
an account created without one starts in — the administrator of Step 6 too,
unless `--lang` names another — and the one the server answers a request in
when the request names no language it speaks. Every user changes their own in
Settings.

### Database roles

The database has two roles, and the application uses the weaker one:

- `DB_USER` (default `inventari_user`) is the administrator. The postgres
  image creates it as the cluster's bootstrap superuser, and Postgres never
  lets that role give up superuser rights. Only the `db-app-role` and
  `db-backup` services, and you during a restore, connect as it.
- `DB_APP_USER` (default `inventari_app`) is what the backend, PgBouncer,
  the migrations and the demo reset connect as. It owns the database and
  everything in its `public` schema — enough for migrations, including those
  a module runs when it is switched on — but it is not a superuser, cannot
  create databases or roles, and so cannot read the server's files or run
  programs on it (`COPY … TO PROGRAM`, `pg_read_file`), whatever SQL reaches
  it.

`db-app-role` creates the application role on the first start and, on every
start, sets its password from `DB_APP_PASSWORD` and hands it whatever in the
database it does not own yet. That is also the upgrade path for an
installation that ran the application as `DB_USER`: add `DB_APP_PASSWORD` to
`.env` and recreate the stack — the first start moves every table, sequence,
view, function and type the old superuser owned over to the application role
(objects of the `pg_trgm` extension stay with the extension). Check it with:

```bash
docker compose -f docker-compose.prod.yml logs db-app-role
# app-role: inventari_app — superuser false, owns N of N relations in public
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql \
  -c "SELECT rolname, rolsuper FROM pg_roles WHERE rolname = 'inventari_app'"
```

The products database behind the `food` profile is split the same way, under
its own names: `products-app-role` runs the same script with that database's
variables, so `PRODUCTS_DB_USER` stays the administrator and
`PRODUCTS_DB_APP_USER` is what owns the products schema. It is described with
the profile in *Optional: the Open Food Facts database* below.

## Sizing the services to the host

The compose file ships limits for a small host, and they stay where they were
until `.env` says otherwise. A host with more memory should say so: the
backend and the database are the two services whose work grows with the
catalogue, and on an 8 GB host the shipped limits left half the memory idle
while the backend's workers were killed for exceeding theirs.

| Variable | What it sets | Shipped |
|---|---|---|
| `BACKEND_MEM_LIMIT` | memory the backend's workers share | `2g` |
| `WEB_CONCURRENCY` | gunicorn workers (see `docs/SCALING.md`, "Connection pool math") | `4` |
| `PGBOUNCER_MAX_CLIENT_CONN` | the connections PgBouncer accepts from the backend; keep it above `WEB_CONCURRENCY` × 50 | `300` |
| `DB_MEM_LIMIT` | memory the database may use | `2g` |
| `DB_SHARED_BUFFERS` | PostgreSQL's `shared_buffers`, about a quarter of `DB_MEM_LIMIT` | `512MB` |
| `DB_EFFECTIVE_CACHE_SIZE` | PostgreSQL's `effective_cache_size`, about the whole of `DB_MEM_LIMIT` | `2GB` |

What to set, with the rest of the stack (proxy, Redis, the backup service, the
frontend) and the system taking about 1.5 GB:

| Host | `BACKEND_MEM_LIMIT` | `WEB_CONCURRENCY` | `PGBOUNCER_MAX_CLIENT_CONN` | `DB_MEM_LIMIT` | `DB_SHARED_BUFFERS` | `DB_EFFECTIVE_CACHE_SIZE` |
|---|---|---|---|---|---|---|
| 4 GB | `1g` | `2` | `300` | `1g` | `256MB` | `1GB` |
| 8 GB | `3g` | `4` | `300` | `3g` | `768MB` | `3GB` |
| 16 GB | `6g` | `6` | `400` | `7g` | `1792MB` | `7GB` |

Raising `WEB_CONCURRENCY` raises the connections the backend opens, 50 per
worker at most (`docs/SCALING.md`, "Connection pool math"), so raise
`PGBOUNCER_MAX_CLIENT_CONN` with it: six workers open up to 300, which the
shipped limit of 300 would leave no room above. What PgBouncer opens to the
database stays its own pool (`DEFAULT_POOL_SIZE: 30` in
`docker-compose.prod.yml`), so the client limit costs the database nothing.

Python does not give the memory of a large answer back to the system, so a
worker replaces itself instead: between requests, once it has grown
`BACKEND_WORKER_MAX_GROWTH_MB` (default `200`) over the size it started at,
and when it has sat idle for `BACKEND_WORKER_IDLE_RECYCLE_SECONDS` (default
`120`; `0` turns this rule off) more than a quarter over that size. The
worker finishes the request it is answering, the arbiter starts a fresh one,
and the log says why: `Replacing worker (pid:…)`. The limit
`BACKEND_MEM_LIMIT` then has to hold `WEB_CONCURRENCY` workers each at their
start-up size plus the growth allowed — about 450 MB each with the defaults —
which is what the shipped `2g` for four workers and the table's numbers leave
room for.

## Optional: the Open Food Facts database

The `products-db` and `products-app-role` services sit behind the `food`
compose profile — the `up -d` commands of the numbered steps do not start
them, and a deployment following those steps runs nine services, not eleven.
Enable the profile only if you want the nutrition module's offline barcode
lookup: name it in `.env`,

```env
COMPOSE_PROFILES=food
```

(`food,offsite` once the off-host copy below is on too). Compose reads that
line for every command run next to the file, so the numbered steps,
*Updating* and *Putting a backup back* reach the two services without a flag.
A `--profile food` typed on one command reaches them for that command only:
the next `up -d --force-recreate` leaves them on the old images, and `down`
leaves them running. The two services come up with the rest of the stack, and nothing has to be
started from here.

The profile needs three more variables in `.env`. Two of them are the split
from *Database roles* above, under the products database's own names:
`PRODUCTS_DB_USER` stays the administrator the image creates (a superuser, for
setup and imports) and `products-app-role` runs the same `app-role.sh` to hand
`PRODUCTS_DB_APP_USER` the schema — that is the role the nutrition module
should be reaching the database as.

```env
PRODUCTS_DB_PASSWORD=<openssl rand -hex 32>
PRODUCTS_DB_APP_PASSWORD=<openssl rand -hex 32>
PRODUCTS_DATABASE_URL=postgresql://products_app:<PRODUCTS_DB_APP_PASSWORD>@products-db:5432/products_db
```

`PRODUCTS_DATABASE_URL` is passed to the backend verbatim — nothing derives it
from the passwords above, so substitute the generated one yourself. An empty
`PRODUCTS_DB_APP_PASSWORD` does not stop `docker compose up` on an install
that never enables the profile (compose reads the whole file before it looks
at profiles); the first start *with* the profile refuses in `products-app-role`
and the backend waits for it, so the failure lands where the profile is used.
Downloading and importing the dataset is covered in
[docs/OFF_DATABASE_SETUP.md](docs/OFF_DATABASE_SETUP.md): a 7.9 GB file of
about 4.8 million products, 13 GB of free disk while it imports and 5 GB
after, about 10 minutes, and 1 GiB of memory in a one-off container of its
own, so the import cannot take down the application's workers.

> **Running a public demo on the same server?** Give it a DNS A record to the
> same address, set `DEMO_DOMAIN=demo.<domain>` in this stack's `.env`, and start the
> demo stack as described in [docs/DEMO.md](docs/DEMO.md#on-the-same-server-as-a-production-install).
>
> **Deploying a public demo instead?** A demo instance rebuilds its database
> from the seed every night and keeps nothing — different enough from a real
> deployment to have its own page: [docs/DEMO.md](docs/DEMO.md).

## Step 5: Deploy — everything but the proxy

```bash
docker compose -f docker-compose.prod.yml up -d --build --scale caddy=0
```

This starts every service except Caddy, the proxy that publishes ports 80 and
443 and puts the installation on the internet. It starts last, in Step 6, once
the administrator exists. With `food` in `COMPOSE_PROFILES` (*Optional: the
Open Food Facts database* below), this command and the one in Step 6 start its
two services too.

The backend migrates the database before it answers. The loop below returns
once it does — on the first start, after the images are built, that is about a
minute:

```bash
until docker compose -f docker-compose.prod.yml exec -T backend \
    curl -sf http://localhost:8000/health/ready >/dev/null; do sleep 5; done
```

Nothing outside the server can reach the installation yet — create the
administrator first.

## Step 6: Create the administrator, then start the proxy

Nothing seeds an administrator. Create it from the server:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py user create-admin \
    --email you@example.com --password '<your password>' --name "Your Name"
```

Replace all three placeholders (`--name` is optional and defaults to
"Administrator"). The password needs 8 to 72 bytes, with a lowercase letter, an
uppercase letter and a digit — the command refuses anything less, and also the
known-weak seed passwords such as `Admin123`. Typed this way it lands in the shell's history; a leading space
keeps it out where `HISTCONTROL` includes `ignorespace` (Ubuntu's default).

The first account on an installation is its administrator and its superuser
(`role='admin'`, `is_superuser=true`) — the one who decides who else gets in.
From this moment registration is closed to strangers: every account after the
first needs an invitation or an approved request.

Now start the proxy:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Without `--scale`, `up -d` starts Caddy and leaves the services already
running as they are. Caddy obtains the TLS certificate from Let's Encrypt
within a minute or two. If the address does not answer over HTTPS yet:

```bash
docker compose -f docker-compose.prod.yml logs caddy
```

The organization starts as "My Organization". Sign in at
`https://inventari.example.com` and choose the workspace mode; the same setup
screen asks for the organization's name, and **Settings → General** changes it
later.

> **Registering instead.** On an installation with no account, the first
> person to register through the page becomes that administrator — decided
> under an advisory lock, so two at once cannot both win. It works, but the
> installation then belongs to whoever reaches it first, and the address is
> not a secret for long: the certificate Caddy requests when it starts is
> published in public Certificate Transparency logs, which scanners watch for
> new names, often within minutes. The order above is what closes that
> window: the administrator exists before the proxy starts, so there is no
> moment at which the installation is reachable and has no account.
> `create-admin` run after Caddy is already up narrows the window but does
> not close it.

### Locked out: the administrator forgot the password

The sign-in screen's reset link needs outgoing mail (below). On an installation
with none, the only administrator has no link to wait for — the reset happens
on the server, with the command that created the account:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py user create-admin \
    --email you@example.com --password '<a new password>'
```

Run against an existing e-mail address it sets the new password, restores the
administrator role and signs out every earlier session; the name and the
organization stay as they were. `--lang pl` (or `en`, `de`, `fr`, `es`, `pt`)
also sets the language the account opens in; without it the account keeps the
one it has. The sign-in screen says the same when it finds no mail to send.

### Outgoing mail

Invitations, purchase orders and notifications go out through the SMTP server
an organization sets in **Settings → Email**, where **Send Test Email** proves
it. Nothing in `.env` configures mail on a production install. Without it the
application still works: an invitation is created all the same, and you pass
its link on yourself — but nothing reaches anyone by mail.

---

## Updating

An update moves the checkout from one release tag to the next. Read the
release's section in [CHANGELOG.md](CHANGELOG.md) first — an alpha can break
things between releases, and the changelog says which. Each step below exists
because skipping it leaves the installation in a state the next one does not
expect:

An installation brought up before the project name was pinned, from a checkout
whose directory is not called `inventari`, holds its volumes under that
directory's name (`docker volume ls` shows it) and must, before pulling this
release, either keep that name with `COMPOSE_PROJECT_NAME=<directory>` in `.env`
or copy each volume of *Volumes* below to its `inventari_` name — otherwise the
next `up` starts on empty volumes and leaves the data under the old names.

The commands below reach the services of the profiles `.env` names in
`COMPOSE_PROFILES` (*Optional: the Open Food Facts database*, *Copy off the
host*). An installation that enabled `food` or `offsite` with `--profile` on
the command line instead names them there first: step 5 recreates only the
services of the active profiles, and leaves the others on the old images.

```bash
cd /opt/inventari

# 1. A backup taken now: the way back if the update fails. It lands in
#    backups/last/, which keeps only the newest — and step 5 restarts the
#    backup service, which backs up at every start. So copy it aside.
docker compose -f docker-compose.prod.yml run --rm -e BACKUP_ONCE=true db-backup
sudo cp -a backups/last backups/before-update

# 2. The next release: the newest tag `git tag --list 'v*' --sort=-v:refname`
#    prints, in place of <new tag>.
git fetch --tags
git checkout <new tag>

# 3. Variables the example gained since the last update. `.env` belongs to
#    the installation and git never touches it, so a name added to the
#    example stays unset until you look for it. Only-on-the-right lines are
#    the ones the new build will read as empty:
diff <(grep -oE '^[A-Z0-9_]+' .env | sort) \
     <(grep -oE '^[A-Z0-9_]+' .env.production.example | sort)

# 4. Build the images the new release changed. Without this step the recreate
#    below redeploys the old images and the checkout deploys nothing.
docker compose -f docker-compose.prod.yml build --parallel

# 4b. Only for a database created from the development line before v0.11.0
#     was tagged — no release precedes v0.11.0, so an installation from a
#     release tag skips it, now and on every update (run there, it prints
#     "nothing to stamp" and changes nothing). The core migration chain was
#     flattened, so a database created before that release records a revision
#     the new image no longer knows and the backend cannot migrate it on
#     boot. Stop the old backend,
#     stamp the database onto the new baseline, then continue. The command
#     refuses unless the database records the chain's last revision and its
#     schema matches the models short of what the module chains still have to
#     change (they run in step 6), printing what differs; a database from an
#     older release must first be updated to that head with the release that
#     carried it.
docker compose -f docker-compose.prod.yml stop backend
docker compose -f docker-compose.prod.yml run --rm --no-deps \
  --entrypoint python backend manage.py db stamp-baseline

# 5. Recreate the services on the new images.
docker compose -f docker-compose.prod.yml up -d --force-recreate --no-build

# 6. Migrate — 'db upgrade' at head also applies module migrations.
docker compose -f docker-compose.prod.yml exec -T backend \
  python manage.py db upgrade

# 7. Wait until the backend really answers before calling it done.
until docker compose -f docker-compose.prod.yml exec -T backend \
    curl -sf http://localhost:8000/health/ready >/dev/null; do sleep 5; done
```

Step 4b applies once, and only to a database created from the development
line before v0.11.0 was tagged — the project's own installations, or one built
from an untagged checkout: it moves that database onto the release's baseline.
No release was published before v0.11.0, so an installation that began on a
release tag has nothing to stamp. The chain used to grow through two roots and four merges;
it now starts from a single baseline revision, and the revision an older
database records is no longer in the tree, so `alembic upgrade` cannot resolve
it. The stamp is not
a blind write: it requires the database to record the previous chain's last
revision (`docvis01`) and compares the live schema with the models, refusing
on any difference (a column added by an older release, a missing index) and
printing what it found, so a database that has not reached the previous head
cannot be labelled as if it had. The revision check is not redundant: one of
the chain's last revisions rewrote the stored notification links without
touching a table, so the schema alone cannot prove that it ran. After the
stamp, the core revisions that follow the baseline and the modules that are
behind migrate as usual: when step 5 recreates the backend, and again in step 6.

Step 3 is where an update can quietly go wrong. `.env` belongs to the
installation — git never touches it — and the example grows over time. A
variable the new build expects but your `.env` lacks (`DB_APP_PASSWORD`, the
application's own database role — see *Database roles* — `AGE_RECIPIENT`, the
age public key for encrypted backups, `FERNET_SALT`) is read as empty: a
missing `DB_APP_PASSWORD` stops `docker compose up` before anything is recreated, which is at least
loud (an empty `AGE_RECIPIENT` does not stop it — the backups are then simply
unencrypted, and the log says so),
while a dev install without `FERNET_SALT` silently generates a fresh salt per
process and every previously encrypted value (stored API keys) becomes
unreadable after a restart. The diff in step 3 turns that into a five-second
check before anything restarts.

Copy any variable step 3 found into the copy of `.env` you keep off the
server, too. Once the new release has run for a while, remove the copy from
step 1: `sudo rm -r backups/before-update`.

Step 6 repeats migrations the new backend has already run for itself. The
backend's entrypoint migrates on every start — `db doctor` first, then the
core chain and the module chains, under an advisory lock so several replicas
can start at once — and step 5 recreates it on the new images, so the
container comes up, migrates, and only then answers. Running the same
migrations again changes nothing: a migration already applied is one alembic
finds at head and leaves where it is. What the step adds is the result where
you can see it: a migration that fails inside the entrypoint goes to
`docker compose logs backend` and leaves a container restarting under
`restart: unless-stopped` while step 7 waits for an answer that never comes;
run here, the same failure stops the update with the error in front of you.
`db upgrade` applies the module migrations at head too, the same ones the
entrypoint's own pass has just run.

### When an update fails

Migrations only move the database forward, so going back is not undoing them:
it is the previous release with the backup from step 1 put back. Check out the
tag you came from, rebuild, and follow *Putting a backup back* below with
`FROM=before-update`:

```bash
# The tag step 2 moved away from — the release the installation ran before
# this update, not the one the update moved to.
git checkout <the tag you came from>
docker compose -f docker-compose.prod.yml build --parallel
```

## Community modules

Community modules are installed, upgraded and uninstalled by the backend
container's own CLI. That container is the one process with both the database
in reach (upgrade and uninstall write to it) and the module trees mounted.

The container runs as `appuser` (uid 1000), and the two module trees are
bind-mounted from this checkout — which *Step 2* leaves owned by whoever
cloned it, `root` included. Give the container's user write access once, after
the stack is up and before the first install:

```bash
docker compose -f docker-compose.prod.yml exec --user root backend sh -c 'chgrp -R appuser /app/app/modules /frontend-modules && chmod -R g+rwX /app/app/modules /frontend-modules'
```

It changes the group and the write bits, not the owner, so the checkout keeps
working for the user who cloned it. A module command that finds a tree still
unwritable stops before changing anything and prints this command.

From `/opt/inventari`:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py module install \
  https://github.com/publisher/inventari-module-x.git --rev v1.0.0
```

Install from a git tag or commit, never a branch: `--rev` is required for git
sources, so what runs on the server is a decision that can be read back later.
Before the first install, add the publisher's key to `MODULE_SIGNING_PUBLIC_KEYS`
in `.env` as `key_id=<base64 public key>` (the installer's refusal names the
variable when the list is empty), then recreate the backend container so it
receives the value. The package signature is verified before a single file is
copied.

The command finishes by printing the host commands that make the module live —
`docker compose -f docker-compose.prod.yml restart backend` and, for a module
that ships screens, `docker compose -f docker-compose.prod.yml build frontend
&& docker compose -f docker-compose.prod.yml up -d frontend`. Run them.
`module upgrade --rev <newer tag>` and `module uninstall` work the same way and
print the steps that apply; an upgrade runs the module's migrations inside the container and keeps
its data.

The production compose file mounts `backend/app/modules` and
`frontend/src/modules` from this checkout and keeps the tracking file in the
`module_data` volume, so installed modules and their record survive an update
(the build and recreate in *Updating* above do not remove them). The installed
directories are untracked in the checkout, which is also why `git clean -fdx`
must not be run on a deployment that has modules installed. `./backups/`
covers the database and uploads; the module code lives in the checkout and the
tracking file in the `module_data` volume, so a server-level backup has to
include both — *What the nightly backup does not cover* below gives the
commands.

---

## Volumes

The production file pins the Compose project name to `inventari`, so every named
volume is called `inventari_<name>` wherever the checkout lives (set
`COMPOSE_PROJECT_NAME` or pass `-p` to run under another name; the volumes then
carry that one). This is everything the installation keeps outside the checkout
and its `.env`:

| Volume | Holds | In `./backups/`? |
| --- | --- | --- |
| `inventari_postgres_data` | the main database: stock, documents, accounts | yes, as the daily dump |
| `inventari_uploads_data` | photographs and attachments | yes, archived next to the dump |
| `inventari_module_data` | the tracking file of installed community modules | no — back it up with the checkout (*Community modules*) |
| `inventari_caddy_data` | the TLS certificates and the ACME account | no — Caddy orders them again, within the certificate authority's rate limits |
| `inventari_caddy_config` | Caddy's autosaved configuration | no — rebuilt on start |
| `inventari_redis_data` | the response cache and rate-limit counters | no — fills itself |
| `inventari_redis_critical_data` | the token store, including the JWT blacklist | no — see *Cache and token store* |
| `inventari_products_data` | the Open Food Facts database (`food` profile) | no — imported again |

A backup that has to bring the installation back therefore covers `./backups/`,
`.env`, the age private key and `inventari_module_data` — and, when community
modules are installed, their code in the checkout; the rest is cache or
reproducible. The demo (`docker-compose.demo.yml`) runs as its own project,
`inventari-demo`, so its volumes never overlap with these.

---

## Database Backups

The `db-backup` service dumps the main database once a day (at 02:00 UTC) into
`./backups/`, and in the same run archives the uploaded photographs and
attachments — the `uploads_data` volume — next to the dump. A database
restored without them would point at pictures that are gone.

- **Daily** backups, retained for 7 days
- **Weekly** backups, retained for 4 weeks
- **Monthly** backups, retained for 6 months

Every archive of the files is a full copy of them, so the backup folder holds
up to 17 copies of the volume at once (7 + 4 + 6). Photographs barely compress;
plan the disk for that, from the size of the volume today:

```bash
docker compose -f docker-compose.prod.yml exec backend du -sh /app/uploads
```

### What the nightly backup does not cover

The service reaches the database and — through a read-only mount — the
`uploads_data` volume. Four things an installation keeps are outside it, and
covering each is your own decision:

- **The files stored in S3** (`FILE_STORAGE_BACKEND=s3`). Photographs and
  attachments then live in the bucket, and the archive made next to the dump
  is a copy of a volume nothing writes any more. `db-backup` cannot reach the
  bucket: turn on the bucket's versioning, or the provider's own backup for
  it, and keep `FILE_STORAGE_S3_SECRET_KEY` with the rest of `.env` off the
  server. A restore then takes the files from the bucket's own history —
  step 4 of *Putting a backup back* has an empty volume to put back.
- **The `inventari_module_data` volume** — the record of which community
  modules are installed, at which revision (see *Community modules*). An
  update keeps it; nothing archives it.
- **The community module code in the checkout** — `backend/app/modules` and
  `frontend/src/modules` hold the installed modules themselves. They are
  untracked files in the checkout: git never carries them, and the service
  never sees them.
- **The TLS certificates in `inventari_caddy_data`.** Leaving them out
  costs a certificate, not the installation: Caddy orders new ones when the
  stack starts, inside the certificate authority's rate limits. Keep them
  only if those limits matter to you.

Nothing takes the archives below off the host — the offsite mirror sends
only the `*.age` files the service writes — so copy them away with the copy
of `.env`. Take them beside the backup of step 1 in *Updating* (they belong
to the same restore point) and whenever the set of modules changes. Every
name below carries the time it was written — the stamp the dump itself
carries — so a second set taken the same day lands beside the first instead
of replacing it, and the archives next to a dump are the ones that belong to
it. One directory holds them:

```bash
sudo mkdir -p /opt/inventari-archives && sudo chown $USER:$USER /opt/inventari-archives
chmod 700 /opt/inventari-archives   # nobody else can read what lands in it

# The tracking record of installed modules — from the running backend.
docker compose -f docker-compose.prod.yml exec -T backend \
  tar -C /app/data -czf - . > "/opt/inventari-archives/module-data-$(date -u +%Y%m%d-%H%M%S).tgz"

# The certificates — only if you decided above to keep them.
docker compose -f docker-compose.prod.yml exec -T caddy \
  tar -C /data -czf - . > "/opt/inventari-archives/caddy-data-$(date -u +%Y%m%d-%H%M%S).tgz"

# The module trees — run from the checkout this guide has you work in.
tar -czf "/opt/inventari-archives/module-code-$(date -u +%Y%m%d-%H%M%S).tgz" \
  backend/app/modules frontend/src/modules
```

Whether the nightly backups are encrypted is up to you, and
`make backup-status` shows which it is today:

- **`AGE_RECIPIENT` empty (the default).** The dump is plain gzip
  (`<db>-<timestamp>.sql.gz`), readable by root only, and every run logs a
  warning that it is unencrypted. This is the right place to start: you have
  working backups from the first night, and no key to lose. The cost is that
  whoever can read the disk can read the database — password hashes and the
  encrypted organisation secrets included — so do not copy these files off the
  host yourself. The `offsite` copy below will not do it either.
- **`AGE_RECIPIENT` set.** The dump is piped through `gzip` and
  [`age`](https://age-encryption.org) before it is written, so the backup volume
  only ever holds ciphertext (`<db>-<timestamp>.sql.gz.age`). Encryption uses
  the age **public** key; the private key never has to exist on the server, and
  a stolen `./backups/` directory or disk is useless without it.

A backup nobody has restored is a hypothesis, and an encrypted one is a
hypothesis about a key. `make backup-verify`, below, is the way to stop
guessing.

### The backup key pair

Encryption turns on with one command, and it is worth understanding before you
run it:

```bash
make backup-key
```

It generates the pair, prints the **private** key once and writes it nowhere —
not to this disk, not to the repository. Copy it into your password manager
then, off the server. **If that key is lost, every encrypted backup is
unreadable, for anyone** — which is why it is not asked for at startup: a key
made only to get the stack running is a key nobody keeps. The command prints the
`AGE_RECIPIENT=age1…` line for `.env`; put it there and recreate the job:

```bash
docker compose -f docker-compose.prod.yml up -d db-backup
```

The key pair is made with the `age` inside the backup image, so nothing needs
installing; you can run the command on your own machine from a checkout, which
is better still, as the private key then never passes through the server at
all. Plain backups made before the key was set stay where they are until
retention rotates them out — up to six months. Once the first encrypted backup
exists and `make backup-verify` has passed, delete them yourself:
`sudo find backups \( -name '*.sql.gz' -o -name '*.tar.gz' \) -delete` (it
leaves the `.age` files alone). The plain archives of the uploaded files are
copies of your photographs, so they go with the plain dumps.

### Prove it restores

```bash
make backup-verify
```

restores the newest backup into a scratch database next to the live one, checks
that tables came back and drops it again; then it reads the newest archive of
the uploaded files through to its last entry, and records the time only when
both came back. An encrypted backup needs the private key, read from stdin and
never written down — paste it and press Ctrl-D, or send it over ssh from the
machine that holds it:

```bash
ssh you@your-vps 'cd /opt/inventari && make backup-verify' < backup-key.txt
```

Here, `backup-key.txt` is a temporary export from your password manager on your
local machine, in the directory where you run the ssh command. Keep it private
(`chmod 600 backup-key.txt`) and remove it after verification. The repository
ignores `backup-key*.txt` as a safeguard; keep the permanent copy in your password
manager, off the server.

`make backup-status` shows the result:

```text
encryption:     on — new backups are readable only with the private key
newest backup:  inventari_db-20261002-020000.sql.gz.age, 5 h old
newest files:   uploads-20261002-020000.tar.gz.age, 5 h old
restore check:  2026-10-02T09:30:00Z (inventari_db-20261002-020000.sql.gz.age, encrypted)
files check:    uploads-20261002-020000.tar.gz.age read back at 2026-10-02T09:30:00Z
```

Until the check has succeeded once, the last two lines read `never`. Run it after
turning encryption on, and again from time to time: it is the only proof that
the key you kept is the key the backups were made for. Both commands run in the
`db-backup` image, which step 4 of *Updating* rebuilds; after any other kind of
update run `make deploy` first to rebuild it.

### Manual backup

The service backs up at every start and then daily; a manual run is one shot:

```bash
docker compose -f docker-compose.prod.yml run --rm -e BACKUP_ONCE=true db-backup
```

### Putting a backup back

A backup is two files from the same run: `<db>-<timestamp>.sql.gz.age`, the
database, and `uploads-<timestamp>.tar.gz.age`, the uploaded photographs and
attachments (`.sql.gz` and `.tar.gz` without a key). `last/` holds the newest
pair, with `-latest` names pointing at it; the frequency folders hold the
older ones:

```bash
ls -lh backups/last/    # daily/ weekly/ monthly/ hold the older ones
```

**First put the backup out of the service's reach.** `db-backup` backs up at
every start and keeps only the newest run in `last/` — and step 5 below starts
it. Restored straight from `last/`, the backup is gone the moment that start
finishes, and a failed attempt could not be tried again. So copy it into a
folder of its own and restore from there:

```bash
sudo cp -a backups/last backups/restore
FROM=restore
```

After a failed update, step 1 of *Updating* has done this already: use
`FROM=before-update`. For an older backup, copy its two files from `daily/`,
`weekly/` or `monthly/` into `backups/restore/` and use their names in place of
the `-latest` ones below.

An encrypted backup needs the private key on the server for steps 3 and 4:
put it in `backup-key.txt` next to the compose file, and remove it when you are
done (`shred -u backup-key.txt`). For a plain backup, each `--entrypoint age
db-backup --decrypt -i - <file> < backup-key.txt` below becomes `--entrypoint
cat db-backup <file>`, and the file names lose `.age`. The names assume the
default `DB_NAME`, `inventari_db`.

`down` and `up -d` below reach the services of the profiles named in
`COMPOSE_PROFILES`, as in *Updating*: the off-host copy, among them, is
stopped while the backup is put back.

```bash
# 1. Stop the application, keeping its volumes; start the database alone, with
#    the application role in place (the dump hands its tables to that role).
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml run --rm db-app-role

# 2. Put the current database aside and create an empty one in its place.
docker compose -f docker-compose.prod.yml exec -T db sh -c '
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "ALTER DATABASE \"$POSTGRES_DB\" RENAME TO \"${POSTGRES_DB}_before_restore\"" \
    -c "CREATE DATABASE \"$POSTGRES_DB\""'

# 3. Load the dump into the empty database.
docker compose -f docker-compose.prod.yml run --rm -T --no-deps --entrypoint age db-backup \
    --decrypt -i - /backups/$FROM/inventari_db-latest.sql.gz.age < backup-key.txt \
  | gunzip \
  | docker compose -f docker-compose.prod.yml exec -T db sh -c \
      'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q -o /dev/null'

# 4. Put the files back into the uploads volume. Files added since the backup
#    stay where they are; the ones the backup holds come back.
docker compose -f docker-compose.prod.yml run --rm -T --no-deps --entrypoint age db-backup \
    --decrypt -i - /backups/$FROM/uploads-latest.tar.gz.age < backup-key.txt \
  | docker compose -f docker-compose.prod.yml run --rm -T --no-deps --entrypoint tar backend \
      -xzf - -C /app/uploads

# 5. Start everything. db-app-role hands the restored database to the
#    application role, and the backend migrates a backup older than the
#    release forward before it answers.
docker compose -f docker-compose.prod.yml up -d
until docker compose -f docker-compose.prod.yml exec -T backend \
    curl -sf http://localhost:8000/health/ready >/dev/null; do sleep 5; done
```

If step 2 stops on `inventari_db_before_restore` already existing, an earlier
restore left it: look at it, drop it
(`DROP DATABASE inventari_db_before_restore`) and run step 2 again.

Then check what came back: sign in and open a record with a photograph;
`docker compose -f docker-compose.prod.yml logs db-app-role` reports
`owns N of N relations`. The backup service made a fresh backup of the restored
installation when it started — prove it with `make backup-verify`. Once you
trust the result, drop what was put aside:

```bash
docker compose -f docker-compose.prod.yml exec -T db sh -c \
  'dropdb -U "$POSTGRES_USER" "${POSTGRES_DB}_before_restore"'
sudo rm -r backups/$FROM
```

### Copy off the host

Encryption stops a leaked directory; it does not survive losing the host. The
`db-backup-offsite` service mirrors `./backups` to an
[rclone](https://rclone.org) remote, so set one up if you care about that
loss. It needs encryption on: with `AGE_RECIPIENT` empty it refuses to start,
and it only ever sends `*.age` files, so a plain dump never leaves the host. It
sits behind the `offsite` compose profile, because it needs credentials only
you can provide:

```bash
# 1. Create ./rclone.conf next to the compose file (it is gitignored):
rclone config            # e.g. remote named gdrive, then gdrive:Inventari/prod-backups

# 2. Name the destination in .env:
BACKUP_RCLONE_REMOTE=gdrive:Inventari/prod-backups

# 3. Enable the profile in .env (food,offsite with the food profile), so every
#    later command — Updating, Putting a backup back — reaches the service too:
COMPOSE_PROFILES=offsite

# 4. Start it:
docker compose -f docker-compose.prod.yml up -d
```

The remote receives the same `.age` files — the dumps and the archives of the
uploaded files, already encrypted, so a plain remote is enough and rclone crypt
would only encrypt them twice. Each is sent once: the `-latest` names in
`last/` are links to the newest pair, and the copy skips links rather than
uploading the pair a second time under those names. The service re-syncs hourly and logs each pass
at INFO; check the first one with:

```bash
docker compose -f docker-compose.prod.yml logs db-backup-offsite
```

Keep `rclone.conf` off the server too, with the copy of `.env`: on a new
server it is what reaches the remote.

## Rotating the encryption key

Organization secrets — mail passwords, AI connection keys, module settings
marked secret, webhook signing secrets — are encrypted under `ENCRYPTION_KEY`,
or under `SECRET_KEY` on an install that left it empty. A new key leaves every
stored value under the old one, so a rotation keeps the old key readable while
one command rewrites them:

```bash
# 1. In .env: the old key goes to PREVIOUS_ENCRYPTION_KEY, a new one to
#    ENCRYPTION_KEY. On an install that never set ENCRYPTION_KEY the old key is
#    SECRET_KEY's value, and SECRET_KEY may be rotated in the same step.
#      PREVIOUS_ENCRYPTION_KEY=<the old ENCRYPTION_KEY, or the old SECRET_KEY>
#      ENCRYPTION_KEY=<openssl rand -hex 32>
# 2. Recreate the backend: it now writes under the new key and still reads
#    every value written under the old one.
docker compose -f docker-compose.prod.yml up -d backend
# 3. See what would be rewritten, then rewrite it.
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py secrets reencrypt
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py secrets reencrypt --apply
# 4. Empty PREVIOUS_ENCRYPTION_KEY in .env, recreate the backend again, and
#    refresh the copy of .env kept off the server.
docker compose -f docker-compose.prod.yml up -d backend
```

Step 3 is safe to repeat: a value already under the new key is left alone. A
value no key opens is listed and left as it is, and the command exits with 1 —
that secret was lost before this rotation (a changed `FERNET_SALT`, a key
nobody kept) and has to be typed in again on its screen.

Setting `ENCRYPTION_KEY` for the first time on an install that has run without
it needs no `PREVIOUS_ENCRYPTION_KEY`: `SECRET_KEY` is always tried as well. Run
step 3 anyway, so a later `SECRET_KEY` rotation does not need the old value.
`FERNET_SALT` has no such path — see *Step 4*.

## Rebuilding on a new server

A lost server comes back from what was kept off it:

- the copy of `.env` (*Step 4*) — with `ENCRYPTION_KEY` (or `SECRET_KEY`) and
  `FERNET_SALT`, without which the secrets organizations stored cannot be read;
- the age private key, if the backups are encrypted;
- the backups — from the off-host copy, or the `backups/` folder of the old
  disk if it survived — and `rclone.conf` to reach the remote;
- when community modules were installed, the `module-data-…` and
  `module-code-…` archives from *What the nightly backup does not cover*.

Two things are in no backup and need none: the Valkey cache and token store
start empty and fill themselves, and the Open Food Facts database of the `food`
profile is imported again ([docs/OFF_DATABASE_SETUP.md](docs/OFF_DATABASE_SETUP.md)).

1. **Steps 1–3 of this guide** on the new server. Check out the release the old
   server ran, or a newer one — the backend migrates an older database forward
   when it starts; never an older one. Point the DNS record at the new address.
2. **Put the kept `.env` in place** instead of Step 4 — do not generate new
   secrets. Change `DOMAIN` only if the address changed.
3. **Community modules only: put their code back,** before the images are built,
   because the frontend image is built from the checkout. The archive also
   holds the project's own modules, which the checkout already has at the right
   version, so extract only the directories of the community modules (`tar -tzf`
   lists them):
   ```bash
   tar -xzf module-code-<stamp>.tgz \
     backend/app/modules/<module> frontend/src/modules/<module>
   ```
4. **Build the images:**
   ```bash
   docker compose -f docker-compose.prod.yml build --parallel
   ```
   Then put the tracking record back into its volume (community modules only):
   ```bash
   docker compose -f docker-compose.prod.yml run --rm -T --no-deps \
     --entrypoint tar backend -xzf - -C /app/data < module-data-<stamp>.tgz
   ```
5. **Bring the backup to `backups/restore/`.** From the off-host copy, with the
   kept `rclone.conf` next to the compose file and your `BACKUP_RCLONE_REMOTE`
   followed by `/last`:
   ```bash
   sudo mkdir -p backups/restore
   docker run --rm -e RCLONE_CONFIG=/config/rclone.conf \
     -v "$PWD/rclone.conf":/config/rclone.conf:ro -v "$PWD/backups/restore":/data \
     rclone/rclone:1.75.1 copy gdrive:Inventari/prod-backups/last /data
   ```
   From the old disk, copy its `backups/last/` there instead.
6. **Follow *Putting a backup back*** above with `FROM=restore`, from step 1.
   The accounts come back with the database — there is no administrator to
   create; sign in as before.

---

## Monitoring & Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Individual services
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f caddy

# Container status
docker compose -f docker-compose.prod.yml ps

# Resource usage
docker stats
```

### Stock consistency

A record (`Item.quantity`, one row per batch and owner) **is** the stock; a
quant is the records summed per product, shelf, batch and owner, read from the
view `stock_quants_from_records` (the `stock_quants` table is gone — ADR-022).
Nothing needs keeping in step, but two pairs can still quietly disagree: the
shelf (the records' view) against the movement ledger, and the cost layers
against the shelf. The check runs by itself every six hours and warns the
organization's admins when a figure changes; it is also on screen under
**Inventory → Statistics → Reconciliation**:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://your.domain/api/v1/stats/reconciliation
```

The answer is a count and a total gap for each pair
(`quant_move_drift_count`/`quant_move_drift_total` for the shelf against the
ledger, `layer_quant_drift_count`/`layer_quant_drift_total` for the cost layers
against the shelf), the number of product records it was measured over
(`items_scanned`), and the previous scheduled measurement (`previous`). Zero
counts are the healthy answer. A standing gap can be by design, especially in
the cost layers; the figure to watch is one that grows, and worth a look before
it reaches a stock take.

---

## Firewall

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (Caddy redirects to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

---

## Troubleshooting

### SSL certificate not issued

1. Confirm DNS resolves to your VPS:
   ```bash
   dig inventari.example.com +short
   ```
2. Confirm ports 80/443 are open:
   ```bash
   sudo ufw status
   ```
3. Check Caddy logs:
   ```bash
   docker compose -f docker-compose.prod.yml logs caddy
   ```
4. Let's Encrypt has rate limits. For testing, add an `acme_ca` line to the
   global options block that opens `Caddyfile` — the one that already holds
   `email {$ACME_EMAIL}`; a second block of its own is not what Caddy expects:
   ```
   {
     email {$ACME_EMAIL}
     acme_ca https://acme-staging-v02.api.letsencrypt.org/directory
     ...
   }
   ```

### Backend fails to start

```bash
docker compose -f docker-compose.prod.yml logs backend
```

Common causes: missing `SECRET_KEY`, database not ready yet (wait for healthchecks).

### Database connection issues

```bash
docker compose -f docker-compose.prod.yml exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version();"'
```

### Label printer permissions

The server never talks to a printer: the print agent
([print-agent/README.md](print-agent/README.md)) runs on a machine next to it
and fetches the labels over the API. If the printer's device is refused on that
machine (Linux), give the user who runs the agent access to the device's group —
for a serial device usually `dialout`:

```bash
sudo usermod -aG dialout $USER
```

---

## Production Ports

| Port | Service | Notes |
|------|---------|-------|
| 80 | Caddy | Redirects to HTTPS |
| 443 | Caddy | Main entry point |
| 8080 | Frontend (nginx) | Internal only |
| 8000 | Backend API | Internal only |
| 5432 | PgBouncer (`pgbouncer-main`), PostgreSQL (`db`) | Internal only |
| 6379 | Valkey (`redis`, `redis-critical`) | Internal only |

The PostgreSQL instances (`db` and, with the `food` profile, `products-db`)
listen on internal `5432` only; no database port is published to the host in
production. The `5433`/`5434`
mappings seen in `docker-compose.yml` are dev-only conveniences.

---

## Cache and token store: Valkey, not Redis

The `redis` and `redis-critical` services run **`valkey/valkey:9.1.2-alpine`**
(BSD-3-Clause, Linux Foundation). Redis has been RSALv2/SSPLv1 since 7.4, which
is not an open-source licence — Valkey is the fork that stayed permissive, and
it speaks the same protocol, so `REDIS_URL`, `REDIS_CRITICAL_URL` and every
client library are unchanged. The service names stay `redis`/`redis-critical`
so existing connection strings and firewall rules keep working.

**Upgrading a deployment that already ran Redis** needs the volumes dropped.
Valkey 8 will not load an RDB file written by Redis 7.4 — it exits with
`Can't handle RDB format version 12` and the container restart-loops:

```bash
docker compose -f docker-compose.prod.yml down
docker volume rm inventari_redis_data inventari_redis_critical_data
docker compose -f docker-compose.prod.yml up -d
```

Coming from Valkey 8 the volumes stay: 9.1 loads an 8.1.9 RDB in place
(measured with 9.1.1 on the dev stack, 2026-09-26 — `BGSAVE` on 8.1.9, then a
restart on 9.1.1 with the same volume, all keys present and no RDB error in
the log; 9.1.2 is a patch release of the same line).

What is lost with those volumes: the response cache and the rate-limit counters
(both rebuild themselves) and **the JWT blacklist**. Without the blacklist,
tokens revoked before the switch are accepted again until they expire on their
own. Rotate `SECRET_KEY` in the same maintenance window if that matters — it
invalidates every outstanding token instead of un-revoking some, at the cost of
logging everybody out.

---

## Security Checklist

- [ ] Strong random `SECRET_KEY` (`openssl rand -hex 32`)
- [ ] Its own `ENCRYPTION_KEY` (`openssl rand -hex 32`) — encrypts org secrets,
      so `SECRET_KEY` rotates without touching them
- [ ] Strong per-deployment `FERNET_SALT` (`openssl rand -hex 32`), never
      changed after the first secret is saved
- [ ] Strong unique `DB_PASSWORD`, `DB_APP_PASSWORD`, `REDIS_PASSWORD` and, if
      the food profile is enabled, `PRODUCTS_DB_PASSWORD` and
      `PRODUCTS_DB_APP_PASSWORD`
- [ ] The application's database role is not a superuser (`db-app-role` logs
      `superuser false`; with the food profile `products-app-role` logs the
      same for `PRODUCTS_DB_APP_USER` — see *Database roles*)
- [ ] Firewall configured (see above)
- [ ] SSH key authentication enabled, password auth disabled
- [ ] Automatic system updates enabled (`unattended-upgrades`)
- [ ] Backup rotation working (`make backup-status` — a recent backup, and whether it is encrypted)
- [ ] Backups encrypted, or consciously left plain (`AGE_RECIPIENT`, `make backup-key`)
- [ ] If encrypted: private key stored off the server (password manager) and `make backup-verify` has succeeded once
- [ ] Off-host copy enabled or consciously skipped (`BACKUP_RCLONE_REMOTE` + `offsite` in `COMPOSE_PROFILES`)
- [ ] Administrator created before the proxy started (see Step 6)

### Disable SSH password authentication

```bash
# Copy your public key to the VPS (run on your local machine)
ssh-copy-id user@your-vps-ip

# Disable password auth on the VPS
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Check what sshd really uses: a file in /etc/ssh/sshd_config.d/ (cloud
# images often ship one) overrides the line above. This must print "no".
sudo sshd -T | grep -i '^passwordauthentication'
```

If it still prints `yes`, set the same line in the file under
`/etc/ssh/sshd_config.d/` that says otherwise, restart `ssh` and check again.
