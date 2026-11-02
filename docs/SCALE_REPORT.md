# Inventari at warehouse scale

How Inventari behaves when one organization holds a hundred thousand products:
every screen and report a warehouse uses daily, measured against a budget on
the smallest server it is meant to run on. The seeder and the measurement are
described in
[`load_tests/README.md`](../load_tests/README.md#warehouse-scale--one-organization-of-up-to-a-million-products);
the raw results are in [`load_tests/scale/results/`](../load_tests/scale/results/).

## In short

On a 4-core VPS with 8 GB of memory (about PLN 30, or 7 EUR, a month), an
organization of 100 000 products, 300 000 records and 950 000 stock movements
fits in a 1.5 GB database. What a warehouse does on the floor stays fast:
scanning a product or a shelf label answers in 20–80 ms, a record card in
50 ms, a shelf's stock in 70 ms, the product picker in 45–60 ms, and a
200-line purchase order or receipt is written in 1.4 s.

The reads were measured twice. On 2026-10-25 the product list took 0.8–3 s a
page, the location list and tree 1.3–1.7 s, three statistics and the
reconciliation 2.8–29 s, and three reports failed outright. On 2026-10-30,
after the lists stopped reading the whole organization and the heavy reports
moved into the database (tree d522e76), a page of
products takes 70–240 ms, every statistics report answers in under a second
at p95 except the reconciliation (2.3 s), the location tree takes 1.1 s,
and the stock as of a date, the valuation and the sums under the product
list (2.5–3.4 s) are the heaviest reads. The writes and the phone screens
were not measured again: they are still the 2026-10-25 run, where posting a
200-line receipt takes 12 s and undoing it 21 s, and most daily screens on
the phone download the whole location list and are usable only after 10 s to
a minute and a half. Each of these has its cause
named below and is being fixed on its own.

## What was measured

### The organization

`backend/seed_scale_data.py --products 100000` (`make seed-scale
PRODUCTS=100000`) wrote one organization in the shape the posting rules
produce: the building of a business, not of a distribution centre — one
warehouse of 10 zones, racks of 8 shelves, 2 000 shelves in all (2 279
locations with the zones, racks and dock lanes) — holding:

| | 100 000 products |
|---|---|
| Products | 100 000, each with an EAN-13 and a SKU, in 40 categories |
| Locations | 2 279: one warehouse, 10 zones, 250 racks, 2 000 shelves, a receiving zone with 10 dock lanes, and the virtual locations every organization has |
| Records | 300 699, a third of the products batch-tracked (104 550 batches) |
| Stock movements | 948 354 over 400 days, in about 63 600 documents |
| Cost layers | 912 560 |
| Database | 1.5 GB |
| Seeded in | 644 s on the server below (the index rebuild 24 s of it) |

The stock reconciliation run at the end of the seed found it consistent: no
difference between the shelves, the movement journal and the cost layers.

The seeder also wrote a million products once, on the same server: 3 001 490
records, 9 486 577 movements and 9 126 246 cost layers in 10 124 s (2 h 49 min),
with the database still capped at 2 GB at the time. That organization had one
shelf for every 20 products, 56 503 locations, which is not a business anyone
runs, so it was not measured further; two findings from it are in *What is
over budget*. The reconciliation the seeder runs at its end could not finish
on it: it then read every group of stock into Python and needed more than 4 GB.
The same two checks written in SQL found that organization consistent too, in
43 s. The reconciliation compares in the database now (`eece129d7`) and its
memory no longer depends on the size of the organization; it has not been run
on a million products again. The 500 000 and 1 000 000 product tiers are not measured in this
report: what fails at 100 000 has to be fixed before larger sizes say
anything new.

### The machine and the configuration

The demo server, with its nightly demo reset stopped and no one else using it while the
measurement ran:

| | |
|---|---|
| Host | OVH VPS, about PLN 30 (7 EUR) a month |
| CPU | 4 vCPU, Intel Haswell |
| Memory | 7.6 GiB usable, no swap |
| Disk | 72 GB SSD |
| Stack | `docker-compose.prod.yml` as deployed: Caddy, gunicorn with four workers, `DEBUG` off, PgBouncer in transaction mode, PostgreSQL 17 with production's tuning |

Production's compose file caps the backend at 1.5 GB and the database at 2 GB
(`BACKEND_MEM_LIMIT` and `DB_MEM_LIMIT` change them; see *Sizing the services
to the host* in `DEPLOYMENT.md`).
On this host that leaves half the memory idle, so the measurement ran with the
limits sized to it: the database at 4 GB with 1 GB of shared buffers and a
3 GB effective cache, everything else as production sets it; the backend at
2.5 GB, raised to 3.5 GB during the measurement (below). With 100 000 products
the database used 1.2–1.7 GB of its 4 GB.

The backend's memory was the first limit the measurement met, before any
query. Each of the four workers keeps the memory of the largest answer it has
built — a 709 KB location tree, a 5.4 MB zone occupancy, a statistic that read
every record — and they were killed for it: three times at the 2.5 GB limit
during the reads and the phone screens, twice during the full spreadsheet
export, and again after the limit was raised to 3.5 GB (the export once
more, then during the screens), while the host still had 3 GB free. An idle
backend sat at 2.8 GB after the screens had run. (The compose file has
since gained a worker that replaces itself once it has grown past a limit,
`BACKEND_WORKER_MAX_GROWTH_MB`; it was not in place for this run.) The phone screens marked with
a 502 below lost a request to such a kill; the screens that had lost one at
2.5 GB were measured again at 3.5 GB, and the numbers below are the second
run's.

The rate limiter stayed on, as it is on any server reachable from the
internet, and the measurement kept under it by spacing its requests 0.35 s
apart. The server times were taken on the host itself, from the Docker
network straight to the backend: no TLS and no internet in them. The phone
screens ran on a workstation, through an SSH tunnel to the same backend, and
the requests they sent were then timed again on the host
(`measure.py --retime`), so every server time in this report is the host's.

### The budget

| Kind | Budget |
|---|---|
| A lookup (a scan, a card, the picker as it is typed into) | 300 ms p95 server time |
| A list (a page of products, documents, the journal, a shelf's stock) | 300 ms p95 server time |
| A report (statistics, valuation, stock as of a date, occupancy, reconciliation) | 2 s p95 server time |
| A write of a 200-line document | 2 s |
| A screen on the phone profile | usable within its phone budget (`frontend/scripts/phone-budget.json`; 8 s for a screen that file does not name) |
| Bulk work: the full spreadsheet export, an import of 100 000 rows | measured, no budget |

Server time is the wall time of the whole answer, p50 and p95 over 20 runs
(10 for the reads of 2026-10-30; a read whose warm-up answer took over 2 s is
timed 5 times, 3 over 10 s) after a warm-up. "Usable" on the phone is from the navigation until the
heading is on the page, the network has gone quiet and no spinner or skeleton
is left — the moment the data is there to act on. The phone is the phone
budget's: a 360x800 Chromium with the CPU slowed 4x and the network held to
slow 4G.

## Results

The results file holds two runs. The **reads** were measured on 2026-10-30
on the tree at d522e76, after the lists began to read a page instead of the
organization (`c301e08ab`) and the heavy reports moved into the database
(`eece129d7`), on the same server with the production stack, over 10 runs
each after a warm-up (5 for the four reads that took over 2 s to warm up: the
sums under the product list, the reconciliation, stock as of a date and the
valuation), on the organization as seeded again (300 699 records, 948 354
movements). The **writes and the phone screens** are the run of 2026-10-25 on
the dev line of that day, before that change (the run ended at 15:23 UTC, the
change was committed at 22:03 UTC; the exact commit was not recorded); they
were not measured again, and the file names each half's date, tree, machine
and fixtures under `halves`, and the hosting plan's price beside the reads. In the
2026-10-25 run the reads were timed first, on the organization as seeded;
the writes came next and left 40 000 imported records on one shelf; the
requests the phone screens sent were timed after that, on 342 000 records,
which is why a request appears a little slower there than the same read in
the reads table. Each screen was opened once on the phone, so its "median" is
that one run. A status 0 is a request whose connection the server dropped:
the worker answering it was killed. The tables are `measure.py --report` of
[`load_tests/scale/results/100k.json`](../load_tests/scale/results/100k.json).

### Reads (server time)

| Path | Class | 100k p50 / p95 ms |
|---|---|---|
| items: first page | list | 72 / 97 |
| items: search, common word | list | 200 / 237 |
| items: search, one barcode | lookup | 54 / 84 |
| items: filter by category | list | 81 / 98 |
| items: filter by shelf | list | 50 / 74 |
| items: sort by name | list | 76 / 90 |
| items: deep page (last counted) | list | 93 / 130 |
| items: expiring in 30 days | list | 444 / 510 **over** |
| items: low stock | list | 272 / 854 **over** |
| items: aggregates | report | 3,308 / 3,391 **over** |
| scan: product barcode | lookup | 56 / 78 |
| scan: shelf label | lookup | 20 / 28 |
| product lookup by barcode | lookup | 24 / 26 |
| product card: stock | lookup | 24 / 30 |
| record card | lookup | 40 / 49 |
| shelf: its records | list | 49 / 75 |
| shelf: its stock | list | 50 / 67 |
| zone: its stock | list | 102 / 110 |
| stock: first page | list | 44 / 58 |
| batches: first page | list | 64 / 73 |
| location tree | list | 492 / 1,090 **over** |
| locations: first page | list | 170 / 202 |
| occupancy heat map | report | 818 / 1,455 |
| occupancy of a zone | report | 1,700 / 1,818 |
| To do | list | 162 / 185 |
| documents: first page | list | 175 / 188 |
| documents: search by number | lookup | 76 / 125 |
| documents: completed dispatches | list | 225 / 246 |
| document card | lookup | 89 / 102 |
| purchase orders: first page | list | 44 / 49 |
| journal: first page | list | 74 / 112 |
| journal: one product | list | 41 / 57 |
| journal: one shelf | list | 66 / 92 |
| journal: last 30 days | list | 103 / 166 |
| stock as of 90 days ago | report | 2,294 / 2,452 **over** |
| stock as of 90 days ago, one zone | report | 454 / 502 |
| valuation today (stock as of today) | report | 2,462 / 2,475 **over** |
| equipment valuation | report | 19 / 23 |
| stats: overview | report | 19 / 21 |
| stats: by-category | report | 276 / 295 |
| stats: by-location | report | 268 / 881 |
| stats: expiry-forecast | report | 227 / 311 |
| stats: low-stock | report | 399 / 460 |
| stats: consumption | report | 40 / 44 |
| stats: cost-analysis | report | 313 / 751 |
| stats: rotation-analysis | report | 25 / 29 |
| stats: smart-alerts | report | 432 / 995 |
| stats: purchase-patterns | report | 337 / 870 |
| stats: expense-forecast | report | 20 / 25 |
| stats: activity | report | 22 / 26 |
| stats: reconciliation | report | 2,252 / 2,316 **over** |
| picker: "h" | lookup | 69 / 89 |
| picker: "he" | lookup | 54 / 57 |
| picker: "hex" | lookup | 45 / 58 |
| picker: "hex " | lookup | 44 / 54 |
| picker: "hex b" | lookup | 44 / 50 |
| picker: "hex bo" | lookup | 47 / 58 |
| picker: "hex bol" | lookup | 46 / 50 |
| picker: "hex bolt" | lookup | 46 / 61 |
| picker in stock: "hex bolt" | lookup | 45 / 54 |
| picker: by SKU | lookup | 38 / 44 |

### Writes and bulk work (one run)

| Path | Class | 100k ms |
|---|---|---|
| purchase order: create, 200 lines | write | 1,401 |
| purchase order: confirm | write | 93 |
| receipt from the order, 200 lines | write | 1,317 |
| receipt: confirm | write | 109 |
| receipt: post (complete), 200 lines | write | 11,724 **over** |
| receipt: undo, 200 lines | write | 21,228 **over** |
| dispatch 1: create, 8 lines | write | 461 |
| dispatch 1: confirm | write | 1,730 |
| dispatch 2: create, 8 lines | write | 413 |
| dispatch 2: confirm | write | 1,468 |
| dispatch 3: create, 8 lines | write | 397 |
| dispatch 3: confirm | write | 1,293 |
| dispatch 4: create, 8 lines | write | 388 |
| dispatch 4: confirm | write | 1,142 |
| dispatch 5: create, 8 lines | write | 425 |
| dispatch 5: confirm | write | 1,291 |
| picking: start 5 dispatches together | write | 2,069 **over** |
| picking: the pick list | lookup | 137 |
| picking: cancel | write | 59 |
| dispatch 1: cancel | write | 758 |
| dispatch 2: cancel | write | 546 |
| dispatch 3: cancel | write | 494 |
| dispatch 4: cancel | write | 483 |
| dispatch 5: cancel | write | 488 |
| stock take of a shelf: create | write | 1,113 |
| stock take: count 350 records | write | 2,138 **over** |
| stock take: complete | write | 458 |
| export: one zone (xlsx) | report | 509 |
| export: every record (xlsx) | bulk | status 0 |
| import: file 1 of 10, 10,000 rows (csv) | bulk | 624,952 |
| import: file 2 of 10, 10,000 rows (csv) | bulk | 648,435 |
| import: file 3 of 10, 10,000 rows (csv) | bulk | 686,277 |
| import: file 4 of 10, 10,000 rows (csv) | bulk | 729,782 |
| import: 40,000 rows in all (stopped after 4 of 10 files) | bulk | 2,689,445 |

### Screens on the phone (usable, median) and what they download

| Screen | Budget ms | 100k usable ms · API KiB · slowest request p95 ms |
|---|---|---|
| launcher | 8,500 | 6,969 · 9 · 1,218 |
| products | 7,500 | 57,175 **over** **1× 502** · 5,278 · 6,277 |
| stock | 8,000 | 34,045 **over** · 2,004 · 2,024 |
| batches | 8,000 | 7,857 · 34 · 1,553 |
| location tree | 8,000 | 82,491 **over** **1× 500** · 4,657 · 2,893 |
| a shelf | 8,000 | 76,567 **over** **1× 500** · 4,658 · 2,893 |
| a zone | 8,000 | 90,237 **over** **1× 500** · 4,657 · 2,893 |
| occupancy | 8,000 | 39,804 **over** **1× 500** **1× 502** · 11 · 26 |
| todo | 8,000 | 14,329 **over** · 1,314 · 1,328 |
| board | 8,000 | 15,820 **over** · 1,379 · 3,131 |
| receive | 10,000 | 83,886 **over** **2× 502** · 6,362 · 2,893 |
| issue | 11,000 | 11,140 **over** · 732 · 1,625 |
| move | 8,000 | 11,290 **over** · 731 · 1,625 |
| history | 8,000 | 10,259 **over** · 463 · 1,099 |
| register | 8,000 | 6,317 · 11 · 74 |
| a document | 8,000 | 68,312 **over** **3× 502** · 6,852 · 2,893 |
| journal | 8,000 | 36,400 **over** · 2,560 · 2,024 |
| stock as of | 8,000 | 37,957 **over** **1× 500** **1× 502** · 1,985 · 2,081 |
| statistics | 8,000 | 11,880 **over** · 1,045 · 1,328 |
| analytics | 8,000 | 17,038 **over** · 1,531 · 11,080 |
| reconciliation | 8,000 | 25,258 **over** · 1,045 · 25,239 |
| stock takes | 8,000 | not in 120 s **over** **2× 502** · 5,333 · 2,893 |
| purchase orders | 8,000 | 8,883 **over** · 393 · 929 |
| a purchase order | 8,000 | 7,068 · 16 · 80 |

## What is over budget, and why

Every path over budget has its cause read from its query plan (auto_explain
with `ANALYZE` and `BUFFERS`, collected on the same server after the timed
runs) and is being fixed on its own. This section is the 2026-10-25 run: its
figures are that run's, and the reads table above shows which of these causes
the changes since (`c301e08ab`, `eece129d7`) have removed (the three failing
reports answer, the statistics are under a second, the product list under
250 ms). The phone screens, the writes and the bulk work are as measured then,
although the code behind some of them has changed since, which is said where
it applies. Grouped by cause:

**The product list reads every record on every page** (0.8–3.2 s a page,
16.6 s for a deep page, 5.1 s for the sums under it). Each page counts every
record; the filter that hides module-owned stock is written as
`storage_location_id = ANY('{…every location of the organization…}')`, which
the planner answers with an index scan over all 342 000 records to exclude
nothing; sorting by name or paging deep sorts them all; and PostgreSQL's JIT
compiles each of these statements for 0.3–1 s. The launcher's attention
counts (1.2 s) and the picker's first one or two letters (310–360 ms) are the
same kind.

**The daily screens download every location.** The shared location hook of
the frontend asks for two complete lists of the organization's locations —
one to name them, one to offer them — page by page, and the location screens
add the whole tree: 4.6–6.9 MB before a shelf, a zone, the receive screen or
a document is usable, 57–90 s on the phone. Each page of locations also takes
1.4–2.9 s on the server, counting records for every location. (The hook has
since been changed to read the places a screen shows rather than the
organization's set, `dfc9a66ff` and `c2578f653`; the phone screens have not
been measured again.)

**Three reports fail.** Occupancy, stock as of a date and the valuation answer
500: each passes one parameter per product to a single statement, 100 000 to
141 000 of them, past the 32 767 the database driver accepts. The run of a
million products with 56 503 locations showed the same limit from the side of
the locations: past about 32 000 of them the product list, the record card, the
location tree and most statistics fail the same way.

**Statistics read everything.** Low stock (28.6 s) is a nested loop of 12
million buffer reads; smart alerts (6.1 s) and purchase patterns (2.8 s) look
records up by a list of 500 names, which the planner answers through the
trigram index meant for search; the reconciliation (16.9 s) sums every
movement and every record in SQL and then compares 900 000 movement sums with
340 000 record sums in Python —
at a million products that comparison needed more than 4 GB and was killed.
It also ran by itself at every backend start; now it measures an organization
only when its last stored pass is older than its six-hour interval.

**Lists sort or count everything before the page**: stock (478 ms), batches
(1.4 s, a join that discards 2.8 million rows), To do (616 ms, a scan of every
document line; 3.1 s for the "done" view), the journal's last 30 days
(334 ms, a count of 180 000 movements), a zone's occupancy (4.7 s, 5.4 MB).

**Document lists carry every line** of every document: 1 MB for a page of 50,
450 KB for a page of purchase orders; searching a document by number scans
all 950 000 lines twice (1.7 s).

**Posting is a statement per step per line.** Posting a 200-line receipt sent
12 832 statements to the database and undoing it 18 559; they took 2.9 s and
2.4 s inside PostgreSQL, the requests 11.7 s and 21.2 s. The rest is the round
trips and the ORM around them. Creating the same order and receipt takes
1.3–1.4 s. (Posting has since been changed to read reference data once and to
write its rows as sets; by that commit's own count a 200-line receipt sends
764 statements and its undo 1 445 instead of 10 100 and 12 400 (`5639c292f`).
They have not been timed again here.)

**Bulk work does not fit.** The full spreadsheet export builds the workbook in
the worker's memory and was killed at 2.5 GB and again at 3.5 GB; an xlsx
sheet also ends at 1 048 576 rows. An import runs at 62–73 ms a row, a
10 000-row file in one request of 10–12 minutes, each file slower than the
last as its shelf fills; the run was stopped after 40 000 of its 100 000 rows.

**A stock take refused** any location past the first 2 000 of the
organization: the stock-take module read the location list with a cap of
2 000 and looked the counted location up in it. A business with 2 000 shelves
has 2 279 locations. (Fixed since: a stock take reads the counted location's
subtree and ancestors and never the whole list, `5639c292f`.)

**The backend's memory**, described above with the machine.

### What configuration and a cache can do

Asked of the plans:

- **Turning JIT off** (`jit = off`; PostgreSQL's default is on, and no compose
  file changed it when this run was made; `docker-compose.prod.yml` sets it now)
  takes 0.2–1 s off each statement behind the product list,
  its sums, the attention counts and the location tree — a quarter to a third of
  their time. It is the one setting that pays, and the product-list fix
  includes it.
- **More memory for the database does not help.** Every slow plan reads its
  pages from shared buffers, almost none from disk: the 1.5 GB database is
  already in memory. The time goes into reading 300 000 records where 50 are
  shown, not into fetching them.
- **More `work_mem`** would keep three aggregates off disk (the reconciliation,
  stock as of a date, occupancy: 14–48 MB each spill at 16 MB), a few hundred
  milliseconds of reports that take far longer for other reasons.
- **A cache in Redis** (three statistics have one today: overview, rotation
  analysis and expense forecast, kept for 300 s; their rows in the reads table
  are the warmed answers, since the warm-up fills the cache and the first
  answer is not what is timed) would make the second opening of a statistic
  fast and the first one no faster, and lists with filters and search would
  not hit it. For the reports that read
  everything — the reconciliation, low stock — computing them in the
  background and reading the stored result is the cache that also bounds the
  memory; the lists need the queries fixed.

## Reproducing it

On a development stack configured the way production runs:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.loadtest-backend.yml:docker-compose.scale.yml \
  docker compose up -d db redis backend
make db-reset && make db-seed
make create-admin email=admin@example.com password=Admin123 name=Administrator ALLOW_WEAK_PASSWORD=--allow-weak-password
make seed-scale PRODUCTS=100000
(cd frontend && npm run build)
make measure-scale TIER=100k
python3 load_tests/scale/measure.py --report load_tests/scale/results/*.json
```

On a production host, the way this report was measured, see *On a production
server* in [`load_tests/README.md`](../load_tests/README.md#on-a-production-server).

The backend runs the stock reconciliation at start-up, when an organization's
last stored pass is older than six hours, and then every six hours; on a large
organization that pass sums the whole journal and takes a couple of seconds
(2.3 s p95 at 100 000 products, in the reads table), so measure after it has
finished, not beside it.
