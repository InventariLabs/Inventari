# Open Food Facts Database Setup

This guide covers downloading the Open Food Facts (OFF) dataset from HuggingFace and importing it into Inventari's `products_db` PostgreSQL instance.

The OFF database powers the **nutrition** module's barcode lookup — when a user scans an EAN/UPC code, the `OFFScanProvider` queries this local database for instant product enrichment (name, brand, nutriscore, ingredients, etc.) without any external API calls.

## License

The Open Food Facts data is available under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/). By importing this data you agree to the ODbL terms. In particular:

- **Attribution**: wherever the nutrition module shows figures that came from this dataset (items tagged with `off_enriched: true` in their metadata) Inventari names "Open Food Facts" as the source, links to world.openfoodfacts.org, and adds a note that the values are a community estimate to check against the label.
- **Share-Alike**: If you redistribute the OFF data (e.g., via a public API), the derived database must also be offered under ODbL.
- **Produced by**: Open Food Facts contributors — https://world.openfoodfacts.org

---

## Prerequisites

- The Docker Compose stack is running with the `food` profile enabled. Dev
  starts it with `docker compose --profile food up -d`; a production install
  enables the profile with `COMPOSE_PROFILES=food` in `.env` — see *Optional:
  the Open Food Facts database* in
  [DEPLOYMENT.md](../DEPLOYMENT.md#optional-the-open-food-facts-database).
- **Disk**: about 13 GB free while you import, about 5 GB after. The
  Parquet file is 7.9 GB; it is mounted into the import container, not copied,
  so it is on disk once, and you delete it afterwards. What stays is the
  `products_data` volume: 4.6 GB after a full import on the development stack,
  2.3 GB of it the table and the rest write-ahead log (production caps that at
  512 MB with `max_wal_size`).
- **Memory**: about 1 GiB free on the host for the length of the import. It
  runs in a container of its own and peaked at 957 MiB on the October 2026
  snapshot — see Step 3.
- The `products-db` service must be healthy:
  ```bash
  docker compose ps products-db
  ```

---

## Step 1: Download the Parquet File

The OFF dataset is published on HuggingFace at:
**https://huggingface.co/datasets/openfoodfacts/product-database**

### Option A: wget / curl (recommended for servers)

```bash
# 7.9 GB (the October 2026 snapshot: 4.8 million products)
wget -O food.parquet \
  "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"
```

Or with curl:
```bash
curl -L -o food.parquet \
  "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"
```

### Option B: huggingface_hub (Python)

```bash
pip install huggingface_hub
python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='openfoodfacts/product-database',
    filename='food.parquet',
    repo_type='dataset',
    local_dir='.',
    force_download=True,
)
"
```

### Option C: Hugging Face CLI

```bash
pip install huggingface_hub
huggingface-cli download openfoodfacts/product-database food.parquet --repo-type dataset --local-dir .
```

> **Note**: No account or token required — the dataset is public.

---

## Step 2: Configure the Backend

Set `PRODUCTS_DATABASE_URL` in your `.env` with the full connection string
(passed verbatim to the container — no automatic derivation).

In production (`docker-compose.prod.yml`) aim it at `PRODUCTS_DB_APP_USER`
(default `products_app`), not at `PRODUCTS_DB_USER`: `products-app-role`
creates that role on the first start with the `food` profile — owner of the
products schema and nothing more, so a query the nutrition engine passes on
has no superuser behind it. Set `PRODUCTS_DB_APP_PASSWORD` in `.env` first or
that one-shot refuses to run (DEPLOYMENT.md, "Optional: the Open Food Facts
database"):

```env
PRODUCTS_DATABASE_URL=postgresql://products_app:your-strong-password@products-db:5432/products_db
```

The development stack (`docker-compose.yml`) makes no such split — its
`products-db` is its own administrator and the commented line in `.env.example`
names `products_user`.

Do this before the import: the importer reads the same variable, and without
it logs that the products database is not configured and stops.

Recreate the backend so it picks the variable up — `restart` keeps the old
environment:
```bash
docker compose -f docker-compose.prod.yml up -d backend   # production (food in COMPOSE_PROFILES)
docker compose up -d backend                               # development
```

---

## Step 3: Run the Import

Run the importer in a one-off container of its own, with the file mounted
read-only — do not `exec` it in the running backend. The one-off container
gets the backend's memory limit (1.5 GiB in `docker-compose.prod.yml`) to itself;
inside the backend's own container the import would share that limit with the
application's workers, and running out of it would take a worker down with it.

Production, from the directory with `docker-compose.prod.yml` and `food.parquet`:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps \
  -v "$PWD/food.parquet:/data/food.parquet:ro" \
  backend python -m app.modules.nutrition.import_parquet /data/food.parquet
```

Development:

```bash
make off-import FILE=/path/to/food.parquet
```

A batch size other than the default `2000` rows goes after the path
(`... /data/food.parquet 5000`, or `make off-import FILE=... BATCH=5000`).

The script:
- Creates the `off_products_local` table in `products_db` if it doesn't exist
- Reads only the thirteen columns it uses (of the file's 145), batch by batch
  (resilient: row-by-row fallback on batch failures); a column a snapshot
  has dropped leaves its field empty
- Logs progress roughly every 10 000 rows
- Uses `INSERT ... ON CONFLICT DO UPDATE` (idempotent — safe to re-run)

**Measured on the October 2026 snapshot** (7.9 GB, 4 817 586 rows in 4 705 row
groups): 9 min 43 s on an NVMe disk, 4 817 521 rows stored, peak memory
957 MiB in a container limited to 1 GiB. About 700 MiB of that is the file's
own index — 145 columns described for each of its 4 705 row groups — which the
Parquet reader holds from the moment it opens the file; the rest stays flat
from the first batch to the last. Expect a longer run on a slower disk or
CPU.

---

## Step 4: Verify the Import

Connect to the products database and check the row count (in production add
`-f docker-compose.prod.yml` after `docker compose`; development can also use
`make off-count`). The user and database names come from the container's own
environment, so they match whatever `.env` set:

```bash
docker compose exec products-db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM off_products_local;"'
```

Expected: about **4.8 million** rows for the October 2026 snapshot (4 817 521
measured); later snapshots only grow.

Test a lookup:
```bash
docker compose exec products-db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT barcode, name, brand FROM off_products_local LIMIT 5;"'
```

---

## Updating the Database

OFF publishes updated snapshots periodically. To refresh:

1. Download the new `food.parquet`
2. Re-run Step 3

The `ON CONFLICT DO UPDATE` logic means existing products are updated and new ones are added — no manual cleanup needed.

### Automated weekly update (optional cron)

Crontab has no line continuation, so the steps go in a script —
`/opt/inventari/off-update.sh`, executable:

```bash
#!/bin/sh
set -e
cd /opt/inventari
wget -q -O food.parquet "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"
docker compose -f docker-compose.prod.yml run --rm --no-deps -T \
  -v "$PWD/food.parquet:/data/food.parquet:ro" \
  backend python -m app.modules.nutrition.import_parquet /data/food.parquet
rm -f food.parquet
```

and the crontab calls it every Sunday at 3:00 AM:

```
0 3 * * 0 /opt/inventari/off-update.sh
```

---

## Troubleshooting

### `products-db` service not found
The `products-db` service is behind the `food` profile in `docker-compose.yml`.
You must start the full stack with the profile enabled:

```bash
docker compose --profile food up -d        # or: make dev-up-full
```

### `PRODUCTS_DATABASE_URL` not set
`PRODUCTS_DATABASE_URL` is passed **verbatim** from your `.env` to the backend
container (the backend service's `environment` block in `docker-compose.yml`). There is no automatic derivation from
`PRODUCTS_DB_*` variables — you must set the full connection string yourself.
In production it points at the application role, `products_app` (created by
`products-app-role`, see Step 2); development has no split and the commented
line in `.env.example` carries the right value:

```env
PRODUCTS_DATABASE_URL=postgresql://products_app:your-strong-password@products-db:5432/products_db
```

### `products-app-role` refuses to start: the application password is missing
The one-shot creates the products database's application role and refuses to
run without a password for it; the refusal names `PRODUCTS_DB_APP_PASSWORD`.
Set it in `.env` and start the profile again.

### Import is killed (exit code 137)
The container ran out of memory. The import needs about 1 GiB, most of it the
file's index rather than the batch, so a smaller batch size does not help.
Check that it ran through `docker compose run` as in Step 3 — not `exec` in
the backend, where it shares the limit with the application's workers — and
that the host has 1 GiB free (`free -m`) before you start it.

### `pyarrow` not installed
The package is listed in `backend/pyproject.toml`. Rebuild the image:
```bash
docker compose build backend
```

### Barcodes not found after import
Check that the `nutrition` module is enabled for the organization
(**Settings → Modules**) and that the products database is configured
(`PRODUCTS_DATABASE_URL`, Step 2). Then scan a code and read the backend log:
`[OFFScanProvider] Querying OFF database for <code>` means the lookup ran,
`Products database not configured, skipping OFF lookup` means Step 2 is missing,
and `Catalogue already names <code>` or `Active item found` means the
organization already has the product, so the lookup is skipped on purpose.
```bash
docker compose logs backend | grep -i OFFScanProvider
```

---

## Architecture Notes

- **Model**: `OFFProductLocal` in `backend/app/modules/nutrition/models.py`  
  — `barcode` (PK, indexed), `name`, `brand`, `image_url`, `data` (JSON: `nutriscore`, `nova_group`,
  `ingredients`, `nutrient_levels`, `quantity`, `categories`, plus the per-100 g nutriments
  as flat keys such as `energy_kcal`, `proteins`, `sugars`), `created_at`, `updated_at`
- **Import script**: `backend/app/modules/nutrition/import_parquet.py`  
  — entry point: `import_off_parquet(file_path, batch_size=2000)`; run as a module it exits 1 when
  the file is missing, the products database is not configured, or the import stops early
- **Scan provider**: `OFFScanProvider` (priority=50) — registered by the `nutrition`
  module. It answers only codes the organization does not already have; the
  provider order and that rule are documented in
  [`docs/subsystems/SCAN.md`](subsystems/SCAN.md).
- **Database engine**: separate `products_engine` / `ProductsSessionLocal` in `backend/app/database.py`
