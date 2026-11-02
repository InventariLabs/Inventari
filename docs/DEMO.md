# Running a public demo instance

**The public one is [demo.inventari.app](https://demo.inventari.app).** A
visitor clicks **Try the demo** on the sign-in page and lands in an
organization of their own: a temporary administrator account over the seed
described [below](#what-visitors-see) — stock on shelves, documents, assets,
recipes. Other visitors cannot open it, but the mail it sends lands in
[an inbox every visitor reads](#no-email-leaves-the-demo). The same browser
comes back to it, and the nightly rebuild wipes it. The rest of this page is
for running an instance like it.

A demo is a database strangers write to. Within a week of going public it
holds half-finished documents, partners called "test", and an item named
"asdf" — not because anyone was careless, but because trying things out is
exactly what a demo is for. The question is not how to prevent that. It is how
long the mess outlives the visit.

Here, until the next reset — and the mess stays the visitor's own. Every
visitor gets an organization of their own on the first click, so nobody sees
what anybody else typed — the shared mail inbox aside — and the instance is
rebuilt from the seed on a schedule: **nothing in it is meant to survive**.
Say so on the page that links to it, so nobody puts real data in.

## What a demo instance is

The same application as any other deployment, with two differences:

1. It declares itself with `INVENTARI_DEMO=true`. Nothing infers this — a
   database named `inventari_demo` on somebody's laptop is still their laptop,
   and guessing from the name is how a reset finds the wrong machine. The
   compose file sets it for the backend and for the reset service: the backend
   reads it through its settings and switches the organization-level mail
   configuration off, the reset service reads it through its guard.
2. It runs the `demo` compose profile, which adds the service that rebuilds
   the database every night and keeps the visitors' organizations seeded in
   between, and the Mailpit container that catches the mail
   ([below](#no-email-leaves-the-demo)).

Everything else — the modules, the migrations, the seed — is what a normal
install gets.

## Starting one

```bash
cp .env.production.example .env
# edit .env: SECRET_KEY, FERNET_SALT, DB_PASSWORD, DB_APP_PASSWORD, REDIS_PASSWORD,
#            DOMAIN, ACME_EMAIL, and add DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD
#            (your own account, not published)

COMPOSE_FILE=docker-compose.prod.yml:docker-compose.demo.yml \
  docker compose --profile demo up -d
```

The `demo-reset` service rebuilds the instance once at start-up and then daily,
so the demo is populated from the first minute rather than showing an empty
install until the first scheduled run. After every rebuild, and then every
minute, it seeds visitors' organizations until the pool is full (see
[Every visitor gets an organization of their own](#every-visitor-gets-an-organization-of-their-own)).
A rebuild and a backend starting beside it queue on the same PostgreSQL
advisory lock the entrypoint holds around its migrations: the first rebuild
does not cut a migration short, and the backend's first start migrates once.
The first rebuild of a fresh stack also waits until the backend answers its
health check, so the drop never lands under the application's own start-up
seeding.

| Variable | Default | What it does |
|---|---|---|
| `INVENTARI_DEMO` | *(unset)* | Set to `true` by the compose file for the backend and the reset service. On the backend it refuses the organization's own SMTP settings and never uses stored ones — every send goes through the system relay. On the reset service it is the guard's permission to wipe the database. |
| `DEMO_RESET_HOUR` | `3` | Hour (UTC) of the daily rebuild. Pick the quiet part of your audience's day. |
| `DEMO_ADMIN_EMAIL` | *(required)* | **Your own** account on the demo: an organization admin over the organization the rebuild seeds first. Visitors never need it — they get organizations of their own — so do not publish it. No default: compose refuses to start until you choose one. |
| `DEMO_ADMIN_PASSWORD` | *(required)* | Its password. No default; keep it to yourself. |
| `DEMO_ITEMS` | `500` | How many stock rows to seed, into your organization and into each visitor's. |
| `DEMO_SANDBOX_POOL_SIZE` | `3` | Visitors' organizations kept seeded in advance, so a click does not wait for a seed. |
| `DEMO_SANDBOX_DAILY_CAP` | `100` | Organizations handed out between two rebuilds. Past it, the next visitor is told to come back tomorrow, and no more are seeded. Raise it together with `DEMO_UPLOAD_TOTAL_MB` — see the limits below. |
| `DEMO_AI_REQUESTS_MONTHLY` | `20` | AI requests each organization may make between two rebuilds — see [AI on the demo](#ai-on-the-demo). |
| `DEMO_SANDBOX_RATE_LIMIT` | `10/hour` | How often one address may ask for an organization, "Start over" included. |
| `DEMO_UPLOAD_FILE_MB` | `2` | Largest single file a visitor can upload, in megabytes. Lower than the per-endpoint limits of a normal install (10–20 MB). |
| `DEMO_UPLOAD_TOTAL_MB` | `200` | Cap on everything the instance holds in file storage. An upload that would pass it is refused with a message saying uploads open again after the next reset. The total holds for uploads that arrive at the same moment and for every backend worker: the room is checked and taken in one locked step. |

The compose file also keeps mail inside the stack: it starts a Mailpit
container in the demo profile and overwrites the application's system SMTP
settings with it, so nothing the demo sends can reach a real relay whatever
`.env` says. The inbox is published on the demo's own domain (see below); its public
address is derived from `DOMAIN` and needs no `.env` entry.

## On the same server as a production install

Two stacks cannot both publish ports 80 and 443, so on one host the production
stack's Caddy is the front door for both names:

1. Create a DNS A record for `demo.<domain>` pointing at the server.
2. In the **production** stack's `.env`, set `DEMO_DOMAIN=demo.<domain>` and
   `docker compose up -d caddy`. Caddy orders a certificate for that name,
   sends HSTS and forwards the traffic to the demo stack.
3. Start the demo as above, from its own checkout or directory with its own
   `.env`, where `DOMAIN=demo.<domain>`, adding `docker-compose.demo-shared.yml`
   to `COMPOSE_FILE`. That file joins the shared `inventari-edge` network the
   production stack creates (so start that stack first) and publishes no port: its Caddy speaks plain HTTP, orders no
   certificate and is reachable only through the front door. A different
   upstream is `DEMO_UPSTREAM=<host>:<port>` in the production `.env`.

`/mailpit/` and the visitor's real address (for the sandbox rate limit) pass
through the front door unchanged. Further names would be further blocks like
this one; the demo is the only one wanted today.

## No email leaves the demo

Every visitor is the administrator of an organization, so whatever the
application can mail, any visitor can mail: a purchase order to an address they type, an
invitation whose text carries the organization name they chose, a password
reset. Pointed at a real relay, that would put the sending domain on
blocklists within days — and stop the operator's own mail from it.

So the demo has its own SMTP. A Mailpit container in the demo profile catches
every message, and `docker-compose.demo.yml` **overwrites** the system SMTP
settings — host, port, credentials, encryption — with it. Overwritten rather
than defaulted is the point: an operator's `.env` may hold a real relay for
the same domain, and the demo must not inherit it.

The system relay is not the only place a mail server can be configured, and on
a demo the other one is public. Every visitor administers an organization,
so its own SMTP settings would be theirs to write: a host and port they choose would make the demo server open
connections from our address, and mail sent through it would bypass the
inbox. `INVENTARI_DEMO=true` on the backend closes both: the settings cannot
be saved (the save is refused with a translated answer) and stored ones are
never used — every message resolves to the system SMTP, whatever the
organization row holds. The email settings screen shows a note pointing at
the demo inbox instead of the form.

The inbox is public and lives beside the demo:

- URL: `https://<your-domain>/mailpit/` (Caddy adds the route through
  `Caddyfile.demo`; Mailpit itself runs with `--webroot /mailpit`).
- The sign-in screen links to it, so a visitor can read the purchase order or
  invitation that would have gone out without opening the docs.
- **The inbox is one for the whole instance**, not one per visitor: addresses
  typed into any visitor's organization are visible to every visitor until the
  next reset. That is the deal a public demo makes; say so where the demo is
  linked.
- **Read-only from outside.** The route answers GET and HEAD and refuses the
  rest with a 403 (`Caddyfile.demo` holds both rules). Mailpit's API writes as
  well as reads, so publishing the reads also published `POST /api/v1/send` —
  anyone on the internet could drop a message into an inbox every visitor
  reads and hand out a link to it, a page served from your own domain — and
  `DELETE` emptied that inbox for everyone. The three endpoints that make
  Mailpit fetch an address taken from a message (the screenshot proxy, the
  link checker, the HTML checker) are refused for the same reason: nothing
  outside chooses what the demo server fetches. Mail still arrives, because
  the application speaks SMTP to Mailpit inside the stack, which no visitor
  reaches; a visitor reads what the demo sent and cannot add to it or clear
  it.

## AI on the demo

A visitor's organization is created fresh, so nobody has set up an AI
connection in it: the demo's AI comes from the model in the server's `.env`
(`LLM_API_KEY`, `LLM_PROVIDER`, `LLM_API_BASE_URL`, `LLM_MODEL`,
`LLM_CAPABILITIES` — see
[`docs/subsystems/LLM.md`](subsystems/LLM.md#the-environments-model)). The key
is never stored in an organization, so no visitor can read it or point it
elsewhere. Without one, the demo runs with every AI feature reporting "not set
up". Declare `vision` only for a model that passed the connection test's
vision probe, or image recognition is offered and fails.

The photo recognition module (`vision`) is switched on in every demo
organization — the shared admin's and each visitor's sandbox — so Quick Add
shows its photo tab from the first screen. What decides it is the server's
model: the module is enabled only when `LLM_API_KEY` is set and that model is
declared to serve image recognition — `LLM_CAPABILITIES` names `vision`, or
is empty with the `openrouter` provider (the same test the AI Connections
screen uses to call a purpose usable). The `demo-reset` service, which does
the seeding, receives these variables from `.env` through
`docker-compose.demo.yml`, together with the provider and its endpoint. A demo
without such a model leaves the module off rather than show a photo tab whose
button cannot work.

One key serves every visitor, so it is bounded twice:

- **In the application.** Every rebuild writes `DEMO_AI_REQUESTS_MONTHLY`
  into the instance-wide default limits (`ai_requests_monthly`), which every
  organization without limits of its own answers to and no visitor can write.
  The call past it is refused by the application, with the count and the
  limit it measured, before any provider is asked. A limit set by hand in the
  admin panel would not outlive the night: the rebuild drops the schema. The
  worst day is about `(DEMO_SANDBOX_DAILY_CAP + 1) × DEMO_AI_REQUESTS_MONTHLY`
  requests.
- **At the provider.** Set a spending cap on the key in the provider's
  console. It is the bound that holds whatever the application does — a bug,
  a concurrent burst slipping past the count, or a key reused elsewhere.

## Every visitor gets an organization of their own

Visitors do not share a login. On a demo the sign-in page offers **Try the
demo**: one click gives the visitor an organization of their own, seeded and
dressed exactly like the operator's, with a temporary administrator account in
it — an organization admin, never a superuser — and lands them on the
launcher. What one visitor types into the application, nobody else sees — mail
is the exception, because every message lands in the
[public inbox](#no-email-leaves-the-demo) that all visitors read, so an
address typed into a document is visible to them all; a visitor who spoils
their copy spoils only theirs; and "reset on demand" is simply another
organization: the notice under the header carries **Start over**, which asks
once and then opens a fresh one.

The same browser comes back to the same organization — after closing the tab,
after signing out — until the nightly rebuild deletes it, and then gets a new
one. The way back is an HttpOnly cookie naming the sandbox's account, sent only
to the route that hands sandboxes out (`POST /api/v1/demo/sandbox`), and it
opens only an account the pool handed out, never yours. Outside a demo that
route answers 404.

**Seeded in advance.** One organization takes several seconds to seed — 5 to
13 s each at the default 500 items, depending on the machine (onboarding, seed
and showcase), and a full rebuild of the instance 10 to 18 s — which is
too long for a click to wait, and the seed is not code a request may run. So
the `demo-reset` service keeps `DEMO_SANDBOX_POOL_SIZE` organizations ready:
`manage.py demo fill-pool` runs right after every rebuild and then every
minute, and seeds as many as are missing. A click takes one off the pool and
activates its account; until then the account is inactive, with a password
nobody knows. When a burst empties the pool, the visitor reads that new copies
are being prepared and to try again in a minute; the next round refills it.

The pool is kept in the `system_settings` table under `demo_sandbox_pool`,
which no visitor can write: an organization's own settings or its member list
would have let a visitor put their spoiled copy back for the next one to
receive. The rebuild drops it with everything else. Handing a sandbox out is
the first entry in that organization's audit log.

**Limits.** `DEMO_SANDBOX_RATE_LIMIT` counts per address in Redis, like the
sign-in limit; `DEMO_SANDBOX_DAILY_CAP` counts the organizations handed out
since the last rebuild. Each refusal is a plain sentence on the page the
visitor is on — "come back tomorrow", "try again later", "try again in a
minute" — never an error page.

Size the cap against your disk, and against the upload total. Each visitor's
organization added 2 to 5 MB to the database at the default 500 items, and
about 1.3 MB of files: the nine recipe photographs, stored the way an upload
is, so they count against `DEMO_UPLOAD_TOTAL_MB` like a visitor's own files.
At the default cap of 100 that is up to about 500 MB of database and 130 MB
of the 200 MB upload total, leaving about 70 MB for what visitors upload; all
of it goes with the next rebuild. When the upload total is spent, new sandboxes are
still handed out, with their recipes left unphotographed — a sandbox without
photographs beats none. Raising the cap means raising `DEMO_UPLOAD_TOTAL_MB`
by about 1.3 MB per extra organization.

## What the reset does

```bash
make demo-reset          # or: manage.py demo reset
```

In order: empties the Mailpit inbox, drops the schema, empties the uploaded
files, re-applies the core and per-module migrations, seeds the installation-wide
data, creates your administrator account, answers the setup wizard (the
Equipment & Warehouse profile, with production and the kitchen modules switched on), seeds the demo rows,
and dresses them for visitors. It ends at
the same place whether it found an empty database or yesterday's demo, which is
what lets a timer call it without knowing which it found.

Emptying the inbox comes first because it is the part that cannot be rebuilt:
the database returns from the seed, a stranger's address in the inbox does not.
If the inbox cannot be emptied — the container restarting, a network hiccup — a
warning is printed and the database rebuild continues: the instance visitors
see must not wait for a mail catcher. `DEMO_INBOX_API_URL` names the inbox API;
unset, as in a local `make demo-reset`, there is nothing to empty.

The uploaded files — item images and attachments visitors added — are removed
right after the schema is dropped: the rows that pointed at them are gone, and
nothing could reach the files again. The `demo-reset` service mounts the same
`uploads_data` volume as the backend for this, and the step sits behind the same
guard as the drop, so an instance that refuses to drop its schema keeps its
files. It empties the directory's contents and leaves the directory itself
(a mount point). It runs before the seed, so the photos the seed stores for
the demo recipes are written afterwards and survive. As with the inbox, a
failure to empty the directory prints a warning and the rebuild continues.

With object storage (`FILE_STORAGE_BACKEND` other than `local`) there is no
directory on that disk, and the same step empties `FILE_STORAGE_S3_BUCKET`
instead: every object in the bucket is deleted — every version of it and
every delete marker, so a file this reset took away cannot be fetched back
through an old version id — at the same point in the sequence and behind
the same guard, the bucket itself stays, and the seed writes its
photographs back afterwards the same way it does on disk. An S3-compatible
store that keeps no versions — Cloudflare R2 implements no versioning
operation — is emptied through the listing it does answer, where its keys
are everything it holds. A bucket that cannot be emptied, one that cannot
be reached or a store that will not say what it holds, is the same warning
rather than a halt. So point the demo at a bucket of its own — the whole
bucket goes with every reset, exactly as the uploads volume does — and give
the process that runs the reset the same `FILE_STORAGE_*` settings the
backend has: the reset service is a container of its own, and compose passes
a service only the variables its `environment:` block names. The upload caps
in the table above (`DEMO_UPLOAD_FILE_MB`, `DEMO_UPLOAD_TOTAL_MB`) are
enforced on local storage only (`backend/app/core/demo_upload_cap.py`); with
object storage nothing but the per-endpoint limits and the bucket's own
quota bounds what visitors upload.

The demo rows come from `backend/seed_demo_data.py`, the seed every stack runs
(`make db-seed-demo`, the QA fixture, the test suite); its rows carry a `SEED-`
marker so `--clean` can find them again. The last step,
`backend/seed_demo_showcase.py`, runs only here: the demo is dropped rather
than cleaned, so it takes the marker off every row a visitor reads, names the
organization, and fills the screens the shared seed leaves empty.

It then sets the AI ceiling (see [AI on the demo](#ai-on-the-demo)).
Afterwards the rebuild time is stored on the organization as
`settings.demo_last_reset_at`, so the instance can say how old it is without
anyone reading container logs.

**Everything is destroyed**: every organization, user, item, document and
uploaded file reference in the database, visitors' organizations and the pool
included. The reset does not spare accounts visitors created, and it is not a
backup boundary — there is nothing here to back up. The `demo-reset` service
refills the pool right after.

## Logs

The nightly reset deletes everything a visitor entered, and the one piece of
personal data it leaves behind is the network address in the servers' logs: the
gunicorn access log of the backend lists the address of every request (the
visitor's own, read from `X-Forwarded-For`), and a failed sign-in or a message
the demo sends adds an email address. Docker keeps those in each container's
`json-file` log, which it never ages out.

The demo is bounded in two ways, and the privacy page tells visitors the second
one:

- **By size, in the compose file.** `docker-compose.demo.yml` gives every
  container three log files of 10 MB, so a flood of requests cannot fill the
  disk.
- **By age, on the host: seven days.** Docker has no age limit for a log, so
  `scripts/demo-prune-logs.sh` removes the lines older than that. Run it once a
  day as root, since the logs belong to the Docker daemon:

  ```bash
  17 4 * * *  /path/to/inventari/scripts/demo-prune-logs.sh
  ```

  It finds the containers of the `inventari-demo` compose project (set
  `INVENTARI_DEMO_PROJECT` if you named it otherwise), stops the ones that are
  running, drops every line dated more than seven days ago from their logs and
  the rotated files beside them, and starts them again. The stop is deliberate:
  Docker appends to the active log with no lock, so a log rewritten under a
  running container loses the lines written meanwhile. The one container it
  does not stop is `demo-reset`, which rebuilds the demo every time it starts:
  that one is paused for the rewrite and resumed, so pruning never causes a
  second wipe. The demo is down for a few seconds at 04:17, and the script
  starts the containers again even when the rewrite fails. `scripts/demo-prune-logs.sh 3` keeps three days instead;
  if you change the number, change the sentence on the privacy page too
  (`privacy.requests.demo` in `frontend/src/i18n/locales/*/auth.json`).

Seven days is the usual figure and is chosen for a reason: a public demo takes
uploads and shows an inbox every visitor reads, and a report of abuse that
arrives a day or two later has only the logs to go on. A shorter period would
leave nothing to look at on a Monday for what happened on Friday night.

To check it, ask Docker where a container's log is
(`docker inspect -f '{{.LogPath}}' <container>`), look at the oldest `"time"`
in that file, run the script, and look again: the oldest line is now less than
seven days old.

The host's own logs (`sshd`, the journal) belong to the server, not to the demo
stack, and a demo that shares its host with a production install takes the
production stack's Caddy as its front door: that Caddy writes no access log
unless its owner adds one.

## Where it refuses to run

`demo reset` is the most destructive command in the CLI and the only one meant
to run unattended. `db reset` protects itself by asking the operator to type
the database name; a timer at three in the morning cannot be asked anything, so
this command's protection is a property of the instance instead:

- it runs only on an install that says its data may go — `DEBUG` or `TESTING`
  on, or `INVENTARI_ENV` set to `development`, `staging` or `demo` — and
  refuses whenever `INVENTARI_ENV` (or `ENVIRONMENT`) says **production**, and
- it refuses when `INVENTARI_DEMO` is not set to `true`.

The first is the check `db reset`, `db downgrade` and the `qa` commands make,
with `demo` added: the `demo-reset` service runs on the production compose with
`DEBUG` off, so `docker-compose.demo.yml` sets `INVENTARI_ENV=demo` on it. Only
this command accepts that name. The production compose sets no `INVENTARI_ENV`
at all, which is why the check asks for a positive answer instead of looking for
the word "production".

Both are required. The second exists because the first is not enough: a staging
copy of a customer's database is disposable and has nothing to do with a
demo.

A refusal exits non-zero, explains which condition failed, and **does not touch
the database** — so adding `docker-compose.demo.yml` to a real deployment by
accident does nothing at all. The guard is covered by
`backend/tests/unit/test_the_demo_reset_refuses_a_real_instance.py`, including
the case that would otherwise pass silently: that a correctly declared demo is
still allowed to run, because a guard which refuses everything is an outage
rather than a safeguard.

The install check is one function, `check_disposable_install` in
`backend/app/cli/__init__.py`, shared by every destructive command. Its refusal
prints the three values it read (`DEBUG`, `TESTING`, `INVENTARI_ENV`) and
touches nothing. Covered for `db reset`, `db downgrade` and `demo reset` by
`backend/tests/unit/test_the_destructive_commands_refuse_an_install_that_is_not_disposable.py`,
and for the `qa` commands by
`backend/tests/unit/test_the_qa_fixture_refuses_an_install_that_is_not_for_development.py`.

## What visitors see

The seed is written to be read, not just to be large. It is described in
`backend/seed_demo_data.py`; the parts that matter for a demo:

- **English throughout.** Product, partner and place names are seeded into the
  database and never pass through the translation files, so they are written in
  English regardless of the interface language a visitor picks. A gate keeps it
  that way (`backend/tests/unit/test_the_demo_seed_speaks_english.py`).
- **A shelf somebody keeps.** Exactly two expired rows and nine expiring within
  the week, rather than a percentage that put a hundred expired items on the
  first screen, and they are drawn from the fridge — the pantry never leads
  with expired salt. Every product sits in the zone its category is kept in:
  chilled goods in Cold Storage, frozen in the Freezer Zone, drinks on the
  beverage racks. Three products sit on a reorder threshold, so the low-stock
  counter shows a working counter instead of a permanent zero.
- **A sheet of labels worth printing.** Every copy's shelves carry the same
  business shelf codes (`A-01`, `A-01-01`) and every product a barcode drawn
  from its own name, so **Label sheet** in the banner above every screen —
  one A4 of shelves and a handful of products — prints once and scans with a
  phone in any copy a visitor is handed
  (`backend/tests/integration/test_the_demo_label_sheet_scans_in_every_sandbox.py`).
- **No module showing its empty state.** Documents in three statuses, a
  partially received purchase order (its received count comes from a completed
  receipt the seed writes, so the first real receipt adds to it instead of
  replacing it), a finished production run, a closed stock
  take with three discrepancies, three assets checked out to named people, one
  asset in for repair and one with a service history, and a fleet with purchase
  dates and warranties spread so a few have run out and a few are about to.
  The showcase step adds a purchase order half-way through a two-stage
  approval that the administrator decides, an attestation campaign with a
  confirmed and a disputed answer, a printed label batch, putaway rules,
  reorder points (one already crossed), supplier price lists, and a phone
  checked out to the administrator for "My Assets"
  (`backend/tests/integration/test_the_demo_instance_is_dressed_for_visitors.py`).
- **An approval the visitor can finish.** The visitor is the only person who can
  sign in, and a requester cannot decide their own request, so the showcase
  step turns on the approvals setting that lets an administrator do it. An
  order they confirm without prices, or over the limit, goes through both
  stages by their own hand. `frontend/tests/e2e/demo-order-without-prices.spec.ts`
  walks it in a browser and passes over any instance that is not a demo: on one
  built as above, run it with `DEV_ADMIN_PASSWORD` set to the operator's password
  and `--project=chromium --no-deps`.
- **The outbound path, walked once.** One picking session crosses two
  dispatches, its lines in the shelves' walk order — the demo's shelves carry
  walk numbers, so the pick order is this warehouse's route rather than
  whatever the random shelf codes spell. One of the two is packed into two
  boxes with a packing slip and goes out under a carrier with a tracking
  number; two more dispatches stand confirmed and untouched, so a visitor can
  pick them themselves. Every confirmed dispatch holds its stock as Confirm
  does, so Available reads below On hand for the goods they will take
  (`backend/tests/integration/test_the_demo_seed_shows_the_outbound_path.py`).
- **A history, not a snapshot.** Stock arrives over the last ten weeks —
  chilled food days ago, equipment on its purchase date — and each record
  opens on that day, movement and cost layer both. Documents are confirmed
  hours after they are written and completed the next day. The production run
  is made the way the application makes one: it draws its three priced
  ingredients from the shelves and puts the jars on one.
- **No seed marker on screen.** Shelf codes read `LOC-…`, as the application
  writes them; the stock take, the orders and the organization have names a
  business would give them.
- **A kitchen with decisions in it.** Nine recipes, some fully on the shelf and
  some one ingredient short, so "I can cook" separates them; this week's meal
  plan, and the shopping list for what the plan is missing. Each recipe has a
  photograph, stored by the showcase step through the same path as the recipe
  page's "Add photo".
- **Nothing that belongs to anybody.** Barcodes come from the GS1
  restricted-distribution range, which is reserved for in-store use and never
  allocated to a real product. Contact details use the domains and telephone
  ranges reserved for documentation. Suppliers and customers are invented;
  manufacturers are the firms that really make the hardware in the rack, which
  is a description rather than a claim about who trades with anyone. The recipe
  photographs are CC0 — free to copy and change with no notice owed — and
  `backend/seed_assets/demo_recipes/sources.json` names the page, author and
  licence of each; a test refuses a photograph without a row there or under
  any other licence.
