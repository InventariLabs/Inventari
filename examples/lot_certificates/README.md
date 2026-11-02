# Lot certificates — an example module

Every received lot carries the number of its certificate, and no receipt is
booked while that certificate is not on file. It is the worked example of
[`docs/MODULE_ADVANCED_GUIDE.md`](../../docs/MODULE_ADVANCED_GUIDE.md),
"Extending the warehouse", and a community module like any other: it imports
the platform only through the module SDK (`app.core.module_sdk`), the contract
DTOs (`app.core.contracts`), the public Core API (`app.core.public_api`) and
the warehouse's public API (`app.modules.warehouse.warehouse_api`), and the
test suite installs it with `module install`.

What it plugs into the warehouse, and where:

| Seam | Here |
|---|---|
| A required field on receipt lines (`meta_data`, two screen slots) | `examples/lot_certificates/backend/seams.py` `require_certificates`, `examples/lot_certificates/frontend/components/` |
| A receiving rule (a pre-post check) | `examples/lot_certificates/backend/seams.py` `require_certificates`, at `post` |
| A pick order (a registered strategy) | `examples/lot_certificates/backend/seams.py` `by_zone_then_weight` |
| A column, a filter and an action on the documents | `examples/lot_certificates/frontend/module.ts`; the filter's server half is `examples/lot_certificates/backend/seams.py` `certified` |
| Its own table and migration chain | `examples/lot_certificates/backend/models.py`, `examples/lot_certificates/backend/migrations/` |

## Trying it

```bash
docker compose exec backend uv run python manage.py module install \
  /repo/examples/lot_certificates --allow-unsigned
docker compose restart backend
docker compose restart frontend
```

The installer prints both restarts. The backend one loads the module's rules;
the frontend one its screens — the certificate field on a receipt line and the
*Certified lots* filter are not there until the frontend has restarted. The
module requires the Warehouse, so enable *Warehouse* first, then *Lot
certificates* for the organization, and choose *Zone by zone,
heaviest first* as the picking order in the warehouse settings.
`make e2e-example-module` uses the currently selected stack; it walks a receipt
and a pick through the browser and uninstalls the module again. Select a
disposable test stack before running it, for example:

```bash
./scripts/dev2 docker compose up -d --build
./scripts/dev2 make db-seed
./scripts/dev2 make create-admin email=admin@example.com password=Admin123 name=Administrator ALLOW_WEAK_PASSWORD=--allow-weak-password
VITE_API_URL=http://127.0.0.1:5273 ./scripts/dev2 make e2e-example-module
```

The target does not provision or reset that stack, and the example's data
remains after uninstalling it.
