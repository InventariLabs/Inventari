# Installing Inventari at home

For a Linux computer at home — a spare PC, a mini PC, a Raspberry Pi — that
the household opens from their phones. There is no domain to buy and no port
to open on the router.

## Install

On that computer, run:

```bash
curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- home
```

It asks for the administrator's e-mail address and password — 8 characters
or more, with a lowercase letter, an uppercase letter and a digit. Then it
puts the computer on [Tailscale](https://tailscale.com), a private network
for your own devices that is free for a household: it prints a Tailscale
address to open in any browser, where you sign in or create the account. The
first time, it also asks you to switch on HTTPS for that network in
Tailscale's admin page, and says where. Then it works on its own for a few
minutes, and ends with the address:

```text
Inventari 0.14.0 is running at

    https://box.tail1234.ts.net
```

`box` is the computer's name and `tail1234` your network's; yours differ.

What the computer needs:

- Linux, 64-bit (amd64 or arm64), with 4 GB of memory or more, left on.
  Ubuntu 26.04 LTS and Debian 13 are the ones tested; macOS and Windows are
  not.
- Ports 80 and 443 free (nothing else serving web pages on it).
- Root, or an account that may use `sudo`.

## Why HTTPS, even at home

A browser lets a page use the camera only when it is sure the page is the
one it asked for: an `https://` address with a certificate it trusts. Staying
signed in needs the same: Inventari keeps your sign-in in a cookie marked
*Secure*, which a browser does not keep for a plain `http://` address. That
is why the installation answers on `https://` only. Over plain `http://`:

- **The camera does not start.** The scan screen shows no picture but
  *Camera error* and *Camera requires HTTPS or localhost. Please check your
  connection.*, with a field to type the code by hand.
- **The sign-in does not last.** It works until the page is reloaded or the
  app reopened, and then the sign-in screen is back.

With a certificate the phone does not trust, a warning comes before the app
(*Your connection is not private*). Clicking past it is not the fix: trust
the certificate instead, which is what Tailscale spares you. And typing the
computer's own address (`192.168.…`) leads nowhere: the certificate is issued
for the name, not for the number.

Tailscale is what makes this easy: it gets the computer a certificate for its
`ts.net` name that every phone already trusts, with nothing to install on the
phone but the Tailscale app. *Without Tailscale* below is the other way, with
a certificate each device is told to trust by hand.

## The phones

On each phone, and on any computer that should open Inventari:

1. Install Tailscale — App Store, Google Play, or
   [tailscale.com/download](https://tailscale.com/download).
2. Sign in with the account the installation used, and leave Tailscale
   switched on.
3. Open the address the installation printed and sign in. To keep it as an
   app: *Share → Add to Home Screen* on an iPhone, *⋮ → Add to Home screen*
   on Android.

The address works away from home too, wherever the phone has internet, and
only on devices signed in to your Tailscale network.

**Check that the camera works.** In Inventory, tap **Scan** in the bar at the
bottom of the screen. The browser asks once whether the page may use the
camera; allow it, and the picture appears. Point it at the barcode on any
package: a product you do not have yet opens the new product form with the
code filled in. If the message above shows instead, check that the address
starts with `https://` and ends in `.ts.net`.

## What it did

- Installed Docker, git and Tailscale where they were missing, and signed the
  computer in to your Tailscale network.
- Fetched the release into `/opt/inventari` and wrote
  `/opt/inventari/.env` with `scripts/init-env.sh`: the `ts.net` name and six
  generated secrets, readable by its owner only, plus a line naming the
  release's published images.
- Downloaded those images, started everything except Caddy, the proxy, and
  created the administrator before Caddy started, as on a server
  ([QUICK_DEPLOY.md](../QUICK_DEPLOY.md) says why).
- Started Caddy, which asks Tailscale for the certificate of the `ts.net`
  name, and waited until the address answered over HTTPS.

Run the same line again and it changes nothing and says so. When a step
fails, it says which one and what to check; run the line again once that is
fixed, and it continues from that step.

A Tailscale certificate, like every public one, is listed in public
certificate logs: the computer's name and your network's name become public
there. The address itself answers only inside your Tailscale network.

## Without Tailscale

For a household that does not want a Tailscale account: Caddy issues the
certificate itself, from a small certificate authority of its own, and each
device is told once to trust that authority. It takes more steps on each
device, and the address works only at home.

**1. A name for the computer.** A certificate is issued for a name, and a
phone that types a bare IP address sends none, so the household's devices
need a name that leads to the computer. Two ways, neither needs a domain you
own:

- **The router's local DNS** (most routers have a "local hostnames" or
  "static DNS" page; so does a Pi-hole): map `inventari.home.arpa` to the
  computer's address. Give the computer a fixed address on the router first —
  a DHCP reservation — or the name will point at nothing after a restart.
- **The computer's own `.local` name**, where mDNS runs (Avahi on Linux;
  macOS and iOS speak it natively): `<hostname>.local`, with the hostname
  from `hostname`. Phones on Android may not resolve it; the router's DNS
  is the safer choice there.

The name must end in `.home.arpa`, `.local` or `.internal`: Caddy uses its
own authority only for names no public authority could certify, and asks
Let's Encrypt for any other — a bare word such as `inventari` included,
which then never gets a certificate.

**2. Install.** On the computer, run:

```bash
curl -fsSL https://github.com/InventariLabs/Inventari/releases/latest/download/install.sh | sh -s -- home --local-ca
```

It asks for the name and for the administrator's e-mail address and password,
does what the Tailscale route does without Tailscale, and leaves the
authority's certificate in `/opt/inventari/inventari-root.crt`.

**3. Trust the certificate on each device.** `inventari-root.crt` is public —
it only says *this authority exists* — and it is the only file to share. Send
it to the phone (a message to yourself, a file share, a USB cable), then:

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

**4. Open `https://inventari.home.arpa`** (or the name you chose) on each of
them, sign in, and check the camera as above.

**The authority's key stays on the computer**, in the `caddy_data` volume.
Anyone who holds it can issue a certificate your devices accept, so keep that
computer as private as the rest of the house's network, and install
`inventari-root.crt` only on devices you own.

## Afterwards

Later commands run in `/opt/inventari` as `docker compose …`. When the
installer added your account to the `docker` group, log out and back in once
before using them; until then, put `sudo` in front.

- **Backups** run from the first night and are described in *Database Backups*
  in [DEPLOYMENT.md](../DEPLOYMENT.md#database-backups). At home the backup
  directory sits on the same disk as the database: copy `backups/` to another
  disk or machine, or set up the off-host copy there, or one dead disk takes
  both. Keep a copy of `/opt/inventari/.env` off the computer too, in your
  password manager: no backup contains it.
- **Mail** is not set up. Invitations are still created and you pass the link
  on yourself; a forgotten password is reset on the computer (*Locked out* in
  [QUICK_DEPLOY.md](../QUICK_DEPLOY.md#troubleshooting)).
- **Updating** is the section of that name in
  [QUICK_DEPLOY.md](../QUICK_DEPLOY.md#updating): a backup first, then
  *Updating* in DEPLOYMENT.md.
- **Changing the name later** — renaming the computer in Tailscale, or
  choosing another home-network name — means setting `DOMAIN` in `.env` to
  the new name and running `docker compose up -d`. Caddy gets a certificate
  for it from the same source, so the devices need nothing new.
