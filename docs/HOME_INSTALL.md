# Installing Inventari on a home network

For a computer at home — a spare PC or a mini PC — that the household reaches from phones and laptops on the same Wi-Fi.
There is no domain name, no public address and no open port on the router: the
installation is not on the internet at all.

[QUICK_DEPLOY.md](../QUICK_DEPLOY.md) is the same stack for a server with a
domain, where Let's Encrypt issues the certificate. At home that cannot work —
nobody on the internet can reach the machine to prove it owns the name — so
Caddy, the proxy in front of the application, issues the certificate itself
from a small certificate authority of its own, and each device is told once to
trust it. Everything else is the production stack: the same compose file, the
same database roles, the same nightly backups.

## What you need

- A 64-bit Linux machine that stays on, with 4 GB of memory or more, Docker
  Engine and Docker Compose v2 (`curl -fsSL https://get.docker.com | sh`, then
  `sudo usermod -aG docker $USER` and log in again). Ports 80 and 443 free.
- A name the *household's devices* can resolve to the machine, because a
  certificate is issued for a name and a phone that types a bare IP address
  sends none. Two ways to get one, neither needs a domain you own:
  - **The router's local DNS** (most routers have a "local hostnames" or
    "static DNS" page; so does a Pi-hole): map `inventari.home.arpa` to the
    machine's address. Give the machine a fixed address on the router first —
    a DHCP reservation — or the name will point at nothing after a restart.
  - **The machine's own `.local` name**, where mDNS runs (Avahi on Linux;
    macOS and iOS speak it natively): `<hostname>.local`, with the hostname
    from `hostname`. Phones on Android may not resolve it; the router's DNS
    is the safer choice there.

  The rest of this page says `inventari.home.arpa`; use whatever name you chose.
  The name must end in `.home.arpa`, `.local` or `.internal`: Caddy uses its
  own authority only for names no public authority could certify, and asks
  Let's Encrypt for any other — a bare word such as `inventari` included,
  which then never gets a certificate.

## Step 1: Get Inventari

```bash
sudo mkdir -p /opt/inventari && sudo chown $USER:$USER /opt/inventari
cd /opt/inventari
git clone https://github.com/InventariLabs/Inventari.git .
git tag --list 'v*' --sort=-v:refname | head -3   # the releases, newest first
git checkout v0.13.0                                # the one you install
```

## Step 2: Configure

```bash
./scripts/init-env.sh --domain inventari.home.arpa --email home@inventari.home.arpa
```

It writes `.env` with all six secrets generated (the same command as *Step 3* of
[QUICK_DEPLOY.md](../QUICK_DEPLOY.md)), with two differences from a server with a
domain: the name is the one from above, and the e-mail address is not used at
home, but must not be empty.

Keep a copy of the finished `.env` off the machine: no backup contains it, and
without its `ENCRYPTION_KEY` and `FERNET_SALT` a restored database cannot read
the secrets stored in it.

## Step 3: Start the stack and create the administrator

```bash
docker compose -f docker-compose.prod.yml up -d --build --scale caddy=0
until docker compose -f docker-compose.prod.yml exec -T backend \
    curl -sf http://localhost:8000/health/ready >/dev/null; do sleep 5; done
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py user create-admin \
    --email you@example.com --password '<your password>' --name "Your Name"
docker compose -f docker-compose.prod.yml up -d
```

The first build takes several minutes; on a small machine or a Raspberry Pi,
add `-f docker-compose.images.yml` after `-f docker-compose.prod.yml` in each
command to download the published images (amd64 and arm64) instead of building
them. The password needs at least 8
characters with a lowercase letter, an uppercase letter and a digit. The proxy
starts last, as in QUICK_DEPLOY.md, so nobody can register before the
administrator exists. In `docker compose -f docker-compose.prod.yml logs caddy`
you will see `certificate obtained successfully … "issuer":"local"` within a
few seconds — there is no waiting for Let's Encrypt.

## Step 4: Let each device trust the certificate

A browser warns about a certificate from an authority it has never heard of,
and a phone camera is not available to a page it does not trust (below). The
fix is to hand each device the authority's root certificate once. Copy it out
of the proxy:

```bash
docker compose -f docker-compose.prod.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt ./inventari-root.crt
```

`inventari-root.crt` is public — it only says *this authority exists* — and it
is the only file to share. Send it to the phone (a message to yourself, a file
share, a USB cable), then:

- **iPhone / iPad:** open the file, allow the profile in Settings, install it
  (Settings → General → VPN & Device Management), then switch it on under
  Settings → General → About → Certificate Trust Settings.
- **Android:** Settings → Security → Encryption & credentials → Install a
  certificate → **CA certificate**, and pick the file. Chrome on Android
  respects it; Firefox for Android needs *Use third party CA certificates*
  switched on in its secret settings.
- **Windows / macOS:** double-click the file and add it to *Trusted Root
  Certification Authorities* (Windows) or to the keychain with *Always Trust*
  (macOS). Firefox keeps its own list: Settings → Privacy & Security →
  Certificates → Import.

Then open `https://inventari.home.arpa` on any of them, sign in, and name the
organization in **Settings → General**.

## What HTTPS and the camera need

- **Scanning with the phone's camera** works only on a page the browser
  considers secure: HTTPS with a certificate it trusts. That is what Step 4
  provides. Over plain `http://` the browser offers no camera at all, and a page
  behind a certificate warning is not one to rely on. Everything else in the
  application works either way.
- **Installing the app on the home screen** (the browser's *Add to Home
  Screen*) wants the same trusted HTTPS.
- **The root certificate's key stays on the machine** in the `caddy_data`
  volume. Anyone who holds it can issue a certificate your devices accept, so
  keep that machine as private as the rest of the house's network, and install
  `root.crt` only on devices you own.
- **Away from home the application is out of reach**, by design. If you want
  it outside the house, a private network such as Tailscale or WireGuard that
  puts your phone on the home network is a better route than opening ports.

## Afterwards

- **Backups** run from the first night and are described in *Database Backups*
  in [DEPLOYMENT.md](../DEPLOYMENT.md#database-backups). At home the backup
  directory sits on the same disk as the database: copy `backups/` to another
  disk or machine, or set up the off-host copy there, or one dead disk takes
  both.
- **Mail** is not set up. Invitations are still created and you pass the link
  on yourself; a forgotten password is reset on the machine with the
  `create-admin` command above (*Locked out* in
  [DEPLOYMENT.md](../DEPLOYMENT.md#locked-out-the-administrator-forgot-the-password)).
- **Updating** is the section of that name in DEPLOYMENT.md.
- **Changing the name later** means changing `DOMAIN` in `.env` and running
  `docker compose -f docker-compose.prod.yml up -d` again. Caddy issues a
  certificate for the new name from the same authority, so the devices need
  nothing new.
