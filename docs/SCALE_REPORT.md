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
in a building of about 1 000 locations fits in a 1.5 GB database. What a
warehouse does on the floor stays fast: scanning a product or a shelf label
answers in 20–65 ms, a record card in 35 ms, a shelf's stock in 60 ms, the
product picker in 45–75 ms, and a 200-line purchase order or receipt is
written in 1.3–1.5 s.

The run of 2026-11-23 (v0.13.0) is the reference. A page of products takes
60–85 ms, the deepest page the list offers included (21 s the day before on
v0.12.0 with 2 279 locations), every statistics report but the reconciliation
answers in under 2 s, and the location tree in 154 ms. What is over its
budget is a short list: the stock as of a date, the valuation, the sums
under the product list and the reconciliation (2.3–2.8 s), a few reads that
the database plans badly (below), posting a 200-line receipt (4.5 s) and
undoing it (3.1 s). Bulk work is slow: the full spreadsheet export takes 4
minutes, and an import of 10 000 rows 9 min 16 s, 18 rows a second. On the
phone the screens take 6.8–11.5 s to become usable, a shelf 15.3 s, measured
from a workstation under load.

Three reads took 2.6–4.7 times as long on the plan the database chose by
itself as on a forced custom plan: the barcode search (336 ms against 72 ms),
the list of products expiring in 30 days (387 against 144 ms) and one shelf's
journal (286 against 111 ms). The measurement ran both ways, as shipped and with
`plan_cache_mode` forced to custom plans, and both are below.

## What was measured

### The building

The seeder writes one warehouse and no more, whatever the size of the
catalogue: a small business has hundreds of places to put things, not
thousands, and a shelf of small parts holds hundreds of products. About 1 000
locations is the upper bound this measurement takes for a business, already a
generous one: the catalogue and the movements grow, the building does not.

### The organization

`backend/seed_scale_data.py --products 100000` (`make seed-scale
PRODUCTS=100000`) wrote one organization in the shape the posting rules
produce: one warehouse of 10 zones, 11 racks to a zone and 8 shelves to a
rack, 880 shelves in all (1 019 locations with the zones, racks and dock
lanes) — holding:

| | 100 000 products |
|---|---|
| Products | 100 000, each with an EAN-13 and a SKU, in 40 categories |
| Locations | 1 019: one warehouse, 10 zones, 110 racks, 880 shelves, a receiving zone with 10 dock lanes, and the virtual locations every organization has |
| Records | 300 699, a third of the products batch-tracked (104 550 batches) |
| Stock movements | 948 354 over 400 days |
| Cost layers | 912 560 |
| Seeded in | 715 s on the server below (the index rebuild 38 s of it) |

The stock reconciliation run at the end of the seed found it consistent: no
difference between the shelves, the movement journal and the cost layers.
The run of 2026-11-22 that this one follows measured the seeder's earlier
building, 2 000 shelves in 2 279 locations, which no small business has; its
results are kept as a comparison for the reads and the phone screens.

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

The demo server running v0.13.0, measured in the hours before its nightly reset
(03:00 UTC), which wipes the seeded organization. The server held 8 other
organizations of the demo while it ran:

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
On this host that leaves half the memory idle, so the October measurement ran
with the limits sized to it: the database at 4 GB with 1 GB of shared buffers and a
3 GB effective cache, everything else as production sets it; the backend at
2.5 GB, raised to 3.5 GB during the measurement (below). With 100 000 products
the database used 1.2–1.7 GB of its 4 GB.

The backend's memory was the first limit the October measurement met, before
any query. Each of the four workers keeps the memory of the largest answer it has
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
On 2026-11-23 the workstation was under load (a load average of 26–44 on 24
cores) while the screens ran, so the phone times are pessimistic.

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
(a read whose warm-up answer took over 2 s is timed 5 times, 3 over 10 s)
after a warm-up. An import is timed until its background job is done, not
until the request that queued it is answered. "Usable" on the phone is from the navigation until the
heading is on the page, the network has gone quiet and no spinner or skeleton
is left — the moment the data is there to act on. The phone is the phone
budget's: a 360x800 Chromium with the CPU slowed 4x and the network held to
slow 4G.

## Results

The run of 2026-11-23 on v0.13.0 (`6252f2d`), on the building described
above: 100 000 products, 300 699 records, 948 354 movements, 1 019 locations.
The tables are `measure.py --report` of
[`100k-1000-locations.json`](../load_tests/scale/results/100k-1000-locations.json),
beside the run of 2026-11-22 on v0.12.0 with the building the seeder wrote
before, 2 279 locations
([`100k-2279-locations.json`](../load_tests/scale/results/100k-2279-locations.json)),
and the same reads with `plan_cache_mode` forced to custom plans
([`100k-1000-locations-custom-plan.json`](../load_tests/scale/results/100k-1000-locations-custom-plan.json)).
The earlier October runs are in
[`100k.json`](../load_tests/scale/results/100k.json); their causes are in
*October 2026: what was over budget, and why*.

The reads, the phone screens and the retiming of their requests were run
once; the writes were run again at 00:00 UTC, because the samplers of the
first pass read only the first 50 records of a shelf, all of which carried an
expiry date on this building (880 shelves of about 300 records), and found no
order line to receive. The stock take is the one write whose completion is not
measured: the script counted 50 of the shelf's 483 records and the completion
was refused for the uncounted ones, a defect of the script that is fixed and
has not been run again.

### Reads (server time)

| Path | Class | 2 279 locations p50 / p95 ms | 1 019 locations p50 / p95 ms | 1 019 locations, forced custom plan p50 / p95 ms |
|---|---|---|---|---|
| items: first page | list | 754 / 837 **over** | 61 / 69 | 56 / 66 |
| items: search, common word | list | 180 / 209 | 463 / 488 **over** | 256 / 308 **over** |
| items: search, one barcode | lookup | 52 / 58 | 336 / 359 **over** | 72 / 89 |
| items: filter by category | list | 92 / 98 | 83 / 88 | 70 / 80 |
| items: filter by shelf | list | 72 / 94 | 52 / 63 | 54 / 61 |
| items: sort by name | list | 746 / 801 **over** | 57 / 63 | 60 / 86 |
| items: deep page (last counted) | list | 21,118 / 21,633 **over** | 84 / 98 | 63 / 70 |
| items: expiring in 30 days | list | 39,977 / 40,756 **over** | 387 / 420 **over** | 144 / 154 |
| items: low stock | list | 3,119 / 3,275 **over** | 251 / 338 **over** | 254 / 282 |
| items: aggregates | report | 3,870 / 3,895 **over** | 2,682 / 2,782 **over** | 1,873 / 1,939 |
| scan: product barcode | lookup | 53 / 63 | 64 / 85 | 56 / 62 |
| scan: shelf label | lookup | 18 / 24 | 19 / 23 | 19 / 23 |
| product lookup by barcode | lookup | 22 / 24 | 23 / 30 | 24 / 27 |
| product card: stock | lookup | 22 / 27 | 22 / 26 | 23 / 26 |
| record card | lookup | 38 / 47 | 35 / 41 | 38 / 43 |
| shelf: its records | list | 47 / 61 | 48 / 55 | 50 / 61 |
| shelf: its stock | list | 60 / 66 | 58 / 71 | 45 / 61 |
| zone: its stock | list | 531 / 584 **over** | 71 / 81 | 77 / 94 |
| stock: first page | list | 44 / 53 | 37 / 49 | 167 / 182 |
| batches: first page | list | 76 / 85 | 64 / 75 | 63 / 74 |
| location tree | list | 489 / 981 **over** | 154 / 418 **over** | 161 / 295 |
| locations: first page | list | 183 / 210 | 192 / 232 | 175 / 186 |
| occupancy heat map | report | 1,001 / 1,643 | 705 / 895 | 630 / 851 |
| occupancy of a zone | report | 1,696 / 1,898 | 1,349 / 1,481 | 1,485 / 1,619 |
| To do | list | 174 / 188 | 146 / 171 | 136 / 157 |
| documents: first page | list | 184 / 211 | 184 / 197 | 165 / 188 |
| documents: search by number | lookup | 75 / 91 | 76 / 87 | 78 / 94 |
| documents: completed dispatches | list | 226 / 239 | 249 / 337 **over** | 191 / 225 |
| document card | lookup | 87 / 108 | 94 / 112 | 90 / 113 |
| purchase orders: first page | list | 42 / 54 | 44 / 49 | 44 / 51 |
| journal: first page | list | 73 / 97 | 75 / 90 | 74 / 83 |
| journal: one product | list | 24 / 41 | 25 / 40 | 38 / 40 |
| journal: one shelf | list | 64 / 78 | 286 / 312 **over** | 111 / 131 |
| journal: last 30 days | list | 106 / 148 | 109 / 150 | 78 / 87 |
| stock as of 90 days ago | report | 3,476 / 3,784 **over** | 2,712 / 2,822 **over** | 2,498 / 2,526 **over** |
| stock as of 90 days ago, one zone | report | 816 / 1,357 | 639 / 666 | 416 / 427 |
| valuation today (stock as of today) | report | 3,290 / 3,503 **over** | 2,655 / 2,710 **over** | 2,576 / 2,586 **over** |
| equipment valuation | report | 18 / 23 | 18 / 19 | 18 / 20 |
| stats: overview | report | 19 / 20 | 19 / 24 | 21 / 23 |
| stats: by-category | report | 762 / 859 | 302 / 316 | 150 / 173 |
| stats: by-location | report | 1,398 / 1,998 | 208 / 348 | 177 / 329 |
| stats: expiry-forecast | report | 439 / 836 | 275 / 290 | 127 / 137 |
| stats: low-stock | report | 554 / 585 | 421 / 434 | 326 / 349 |
| stats: consumption | report | 47 / 55 | 39 / 44 | 39 / 45 |
| stats: cost-analysis | report | 1,224 / 1,750 | 970 / 1,036 | 578 / 594 |
| stats: rotation-analysis | report | 29 / 66 | 25 / 36 | 25 / 36 |
| stats: smart-alerts | report | 2,988 / 3,782 **over** | 1,698 / 1,808 | 1,461 / 1,662 |
| stats: purchase-patterns | report | 629 / 728 | 108 / 129 | 96 / 107 |
| stats: expense-forecast | report | 20 / 26 | 19 / 24 | 19 / 25 |
| stats: activity | report | 24 / 32 | 22 / 28 | 84 / 93 |
| stats: reconciliation | report | 2,228 / 2,504 **over** | 2,277 / 2,348 **over** | 2,380 / 2,418 **over** |
| picker: "h" | lookup | 70 / 77 | 73 / 79 | 68 / 81 |
| picker: "he" | lookup | 53 / 64 | 55 / 71 | 54 / 63 |
| picker: "hex" | lookup | 47 / 56 | 46 / 54 | 46 / 55 |
| picker: "hex " | lookup | 46 / 58 | 46 / 55 | 45 / 57 |
| picker: "hex b" | lookup | 47 / 52 | 48 / 54 | 47 / 56 |
| picker: "hex bo" | lookup | 48 / 57 | 48 / 57 | 47 / 53 |
| picker: "hex bol" | lookup | 47 / 60 | 48 / 55 | 51 / 59 |
| picker: "hex bolt" | lookup | 48 / 56 | 54 / 76 | 51 / 60 |
| picker in stock: "hex bolt" | lookup | 50 / 56 | 124 / 131 | 115 / 137 |
| picker: by SKU | lookup | 39 / 43 | 41 / 48 | 41 / 51 |


### Writes and bulk work (one run)

| Path | Class | 1 019 locations ms |
|---|---|---|
| purchase order: create, 200 lines | write | 1,484 |
| purchase order: confirm | write | 114 |
| receipt from the order, 200 lines | write | 1,250 |
| receipt: confirm | write | 118 |
| receipt: post (complete), 200 lines | write | 4,463 **over** |
| receipt: undo, 200 lines | write | 3,081 **over** |
| dispatch 1: create, 8 lines | write | 489 |
| dispatch 1: confirm | write | 1,464 |
| dispatch 2: create, 8 lines | write | 537 |
| dispatch 2: confirm | write | 1,240 |
| dispatch 3: create, 8 lines | write | 463 |
| dispatch 3: confirm | write | 1,565 |
| dispatch 4: create, 8 lines | write | 533 |
| dispatch 4: confirm | write | 2,152 **over** |
| dispatch 5: create, 8 lines | write | 486 |
| dispatch 5: confirm | write | 1,682 |
| picking: start 5 dispatches together | write | 2,903 **over** |
| picking: the pick list | lookup | 192 |
| picking: cancel | write | 53 |
| dispatch 1: cancel | write | 472 |
| dispatch 2: cancel | write | 512 |
| dispatch 3: cancel | write | 719 |
| dispatch 4: cancel | write | 632 |
| dispatch 5: cancel | write | 605 |
| stock take of a shelf: create | write | 427 |
| stock take: count 50 records | write | 357 |
| stock take: complete | write | status 400 |
| export: one zone (xlsx) | report | 80 |
| export: every record (xlsx) | bulk | 238,301 |
| import: 10,000 rows in all, until the job was done | bulk | 555,635 (18 rows/s) |

The posting figures are those of the day before within a second (a receipt
posted in 4.7 s, undone in 3.0 s, five dispatches picked together in 2.0 s).
The full export takes 244 s (the day before) and 238 s, and the import 18
rows a second on both runs: each 10 000 rows of the import took 9 min 16 s
until its background job was done.

### Screens on the phone (usable, median) and what they download

| Screen | Budget ms | 2 279 locations usable ms · API KiB · slowest request p95 ms | 1 019 locations usable ms · API KiB · slowest request p95 ms |
|---|---|---|---|
| launcher | 8,500 | 9,258 **over** · 9 · 21,458 | 6,785 · 10 · 792 |
| products | 7,500 | 11,709 **over** · 270 · 43,432 | 9,842 **over** · 270 · 2,743 |
| stock | 8,000 | 7,003 · 30 · 102 | 7,166 **1× 502** · 30 · 42 |
| batches | 8,000 | 6,834 · 34 · 89 | 7,254 **1× 502** · 34 · 86 |
| location tree | 8,000 | not in 120 s **over** · 1,079 · 1,705 | 10,623 **over** · 492 · 1,005 |
| a shelf | 8,000 | 14,612 **over** · 1,095 · 1,705 | 15,340 **over** **1× 502** · 1,211 · 1,005 |
| a zone | 8,000 | not in 120 s **over** · 1,108 · 1,705 | 10,815 **over** · 506 · 1,005 |
| occupancy | 8,000 | 13,145 **over** · 1,066 · 1,705 | 9,526 **over** · 479 · 1,005 |
| todo | 8,000 | 8,543 **over** · 76 · 611 | 8,967 **over** · 77 · 191 |
| board | 8,000 | 9,265 **over** · 143 · 611 | 9,524 **over** **1× 502** · 144 · 276 |
| receive | 10,000 | 7,369 · 70 · 100 | 7,305 · 70 · 58 |
| issue | 11,000 | 7,799 · 69 · 611 | 7,771 · 68 · 92 |
| move | 8,000 | 7,643 · 68 · 611 | 7,655 · 68 · 92 |
| history | 8,000 | 8,107 **over** · 75 · 195 | 8,230 **over** · 76 · 205 |
| register | 8,000 | 6,706 · 11 · 70 | 7,184 **1× 502** · 11 · 73 |
| a document | 8,000 | 9,231 **over** · 120 · 159 | 9,374 **over** · 117 · 143 |
| journal | 8,000 | 8,556 **over** · 153 · 645 | 10,838 **over** · 156 · 1,173 |
| stock as of | 8,000 | 10,429 **over** · 45 · 3,056 | 9,575 **over** · 45 · 2,702 |
| statistics | 8,000 | 26,460 **over** · 316 · 21,458 | 9,062 **over** **1× 502** · 152 · 1,068 |
| analytics | 8,000 | 27,820 **over** · 954 · 21,458 | 11,455 **over** · 790 · 1,919 |
| reconciliation | 8,000 | 25,879 **over** · 316 · 21,458 | 10,280 **over** · 152 · 2,481 |
| stock takes | 8,000 | 7,638 **1× 502** · 11 · 85 | 7,059 **1× 502** · 11 · 58 |
| purchase orders | 8,000 | 7,342 · 49 · 57 | 7,792 · 49 · 50 |
| a purchase order | 8,000 | 8,248 **over** · 17 · 88 | 7,477 · 17 · 75 |


The location payload is 470 KB (1 057 KB with 2 279 locations). The location tree
and a zone, never usable on 2026-11-22 within the 120 s the script waits,
are usable here in 10.6 and 10.8 s. A 502 is a request lost to a worker that
was killed or restarted while it answered; the browser retries it.

The screens and the script. On 2026-11-22 the tree and a zone were reported
as never usable although their heading came at 5–6 s and the network went
quiet at 14–15 s when opened by hand. The first load of each screen carries
one `history.replaceState` to the address it is already at, which the router
makes as it starts: it is the library's, it loads no second document, and the
script's heading wait now looks for a visible heading rather than the first
in the document. The zone's requests on 2026-11-22 show the application's own
start-up requests twice, 4.4 s apart, which is a second document load; the
application reloads once when a script chunk cannot be fetched
(`frontend/src/lib/staleChunk.ts`); whether a chunk failed that day was not
recorded. The 2026-11-23 run loaded each document once. The script
now records the document loads and the files that failed beside each screen,
and for a screen that never settles, which of the heading, a request in
flight or a loader was missing, so the next occurrence names its cause.

## What is over budget on 1 019 locations

The reads over their budget on 2026-11-23, as shipped and with custom plans
forced:

| Read | As shipped p50 / p95 ms | Custom plans p50 / p95 ms |
|---|---|---|
| items: search, common word | 463 / 488 | 256 / 308 |
| items: search, one barcode | 336 / 359 | 72 / 89 |
| items: expiring in 30 days | 387 / 420 | 144 / 154 |
| items: low stock | 251 / 338 | 254 / 282 |
| items: aggregates | 2 682 / 2 782 | 1 873 / 1 939 |
| location tree | 154 / 418 | 161 / 295 |
| documents: completed dispatches | 249 / 337 | 191 / 225 |
| journal: one shelf | 286 / 312 | 111 / 131 |
| stock as of 90 days ago | 2 712 / 2 822 | 2 498 / 2 526 |
| valuation today | 2 655 / 2 710 | 2 576 / 2 586 |
| stats: reconciliation | 2 277 / 2 348 | 2 380 / 2 418 |

The plan the database chooses explains most of the first rows. Forcing the
plan of the deep page of products to a generic one on this data took 9.5 s (a
nested loop over 1 016 locations and a bitmap scan each) against 19 ms on a
custom one, and the same page took 21 s the day before on 2 279 locations. The
generic plan is still not fixed on v0.13.0: it did not dominate this run, on a
server that held 8 organizations of the demo, not the 17 of the day before. The stock as
of a date, the valuation and the reconciliation do not depend on it: they sum
the whole journal and take 2.3–2.8 s either way.

## October 2026: what was over budget, and why

Every path over budget in the October runs had its cause read from its query
plan (auto_explain with `ANALYZE` and `BUFFERS`, collected on the same server
after the timed runs). The figures are those runs' (2026-10-25 for the writes
and the phone screens, 2026-10-30 for the reads, on 2 279 locations); the
changes since (`c301e08ab`, `eece129d7`) removed several of these causes, as
the tables above show (the three failing reports answer, the statistics are
under 2 s, the product list under 100 ms). The code behind some of the others
has changed too, which is said where it applies. Grouped by cause:

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
