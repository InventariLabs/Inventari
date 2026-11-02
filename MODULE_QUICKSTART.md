# Module Quick Start

Create a module with backend and frontend code, connect it to Inventari and
test it. You can keep the module in its own repository and distribute it
independently, or develop a module inside the Inventari source tree.

Use a running [development environment](CONTRIBUTING.md)
before following the commands below. For the architecture and API reference,
see [MODULES_GUIDE.md](MODULES_GUIDE.md).

---

## Which path is right for you?

| I want to… | Start here |
|---|---|
| Build a module in its own repository for my organization, customers or the community | [Path B: Community module package](#path-b-community-module-package-for-distribution) |
| Develop a module inside the Inventari source tree | [Path A: In-tree module](#path-a-in-tree-module-core-development) |
| Add a field, rule or picking strategy to the warehouse | [Lot certificates example](examples/lot_certificates/README.md) |
| Install, upgrade or uninstall a module | Path B: [install it locally](#2-develop-normally), [publish it](#3-publish), [ship a new version](#4-ship-a-new-version) or [uninstall it](#5-uninstall) |

An independent module has its own package and release history. A pull request
to Inventari is needed when you propose a change to the platform or contribute
a module to this repository; it is not part of distributing your own package.

> **Trust is certification, not a sandbox.** Your module runs in-process with
> the same database and filesystem access as the Core; what makes it safe is
> who reviewed and signed it, not a boundary the platform draws around it. The
> three trust levels, and what `module_type` does and does not decide, are in
> [ADR-019](docs/adr/ADR-019-modules-are-certified-not-sandboxed.md).

---

## Path A: In-tree module (core development)

### 1. Start a branch and create the scaffold

```bash
git checkout dev && git pull
git checkout -b feature/warranty-tracker
make new-module NAME=warranty_tracker
```

This writes two directories and changes six files:

```
backend/app/modules/warranty_tracker/   ← a working copy of the reference module
frontend/src/modules/warranty_tracker/  ← module.ts, pages/IndexPage.tsx, i18n/*.json, and empty components/, hooks/ and types/ folders
backend/app/core/module_safety.py       ← the module joins REPO_SHIPPED_MODULES
frontend/scripts/module-catalog.json    ← the store's catalog snapshot learns it
frontend/scripts/i18n-backend-keys.json ← the snapshot of the labels the backend sends learns its permissions
docs/api/openapi.json                   ← the scaffold's endpoints join the published API schema
frontend/src/types/api-generated.ts     ← generated from that schema
frontend/src/types/api-routes.ts        ← generated from that schema
```

`make new-module` writes all six itself — the last three from the running
backend, so the stack has to be up — and each is a checked-in contract that a
gate compares with the code. They are part of the module, not bookkeeping: the
backend refuses at startup a module that claims to be official from a
directory the repository does not list, the pre-commit hook refuses a catalog
snapshot that disagrees with the manifests, and `make check-frontend` refuses a
key snapshot that does and fails on an OpenAPI schema or generated types that
miss the module's endpoints. When you add or change an endpoint later, `make generate-openapi
generate-api-types` brings those three back in step.

---

### 2. The backend already answers

The backend scaffold is a copy of the reference module, `example_widgets` —
not an empty shell. It arrives with a `warranty_tracker` table (named after the module) and its migration; list,
create, read, update and delete endpoints under `/api/v1/warranty-tracker`;
read and write permissions; a journal entry for every write; and its own
integration tests. The comments in `router.py` and `service.py` say why each
piece is there. Rename `Widget` to what your module holds once you know what
that is.

Two rules come with it. The router is guarded by
`require_module('warranty_tracker')`: an organization that has not switched
the module on gets 403. And your module's own tables you query directly, as
`service.py` does — but Core data (products, places, stock) only through
`core_api`, never through `app.models`. The endpoint below shows that door —
the scaffold's own `core_api` call is the journal entry in `service.py`. Add one
import to `router.py`, beside the `module_sdk` import, and the endpoint
**above** the `/{widget_id}` routes — FastAPI matches paths in order, and
`summary` is not a UUID. `router.py` already has `UUID`, `AsyncSession`,
`get_async_db`, `require_org`, `Depends` and `router` for its own endpoints, so
the endpoint needs no other import; do not paste those lines again, or ruff
reports them as redefinitions:

```python
from app.core.public_api import core_api
```

```python
@router.get('/summary')
async def summary_endpoint(
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> dict[str, int]:
    """How many items the organization holds — Core data, read through core_api."""
    return {'items': await core_api.items.count_async(db, org_id)}
```

> Read and write Core data through `core_api`; that facade and
> `app.core.contracts` (DTOs, `ModuleModelBase`) are the rest of the door beside
> `app.core.module_sdk`. A module the platform does not ship may import from
> those three paths and from its own package only — the install-time scan
> refuses every other `app.` path, except the `<m>_api` door of a shipped module
> that its manifest lists under `requires` — so copy the imports from the scaffold rather than from an in-repo
> module: those predate the door and are held to a frozen list.

> Full CoreAPI reference: `MODULES_GUIDE.md` → *CoreAPI & Data Access*.

---

### 3. Switch it on

```bash
docker compose restart backend    # discovers the module and creates its table
```

Then, signed in as an administrator: **Settings → Modules** (it opens the
module catalog at `/apps`) → **Warranty Tracker** → **Activate**. The API docs
at http://localhost:8005/docs now list the module's endpoints, and
`GET /api/v1/warranty-tracker` answers an empty page:
`{"items": [], "total": 0, "limit": 100, "offset": 0, "has_more": false, "total_capped": false}`.
A list endpoint answers with this envelope rather than a bare array — the
architecture lint refuses `response_model=list[...]` — so a screen can say how
many there are and ask for the next page (`docs/subsystems/PAGINATION.md`).

---

### 4. Show it on screen

Three files in `frontend/src/modules/warranty_tracker/`. What the list
endpoint returns, in `warranty_tracker/types/index.ts`:

```ts
/**
 * One widget as a row of `GET /api/v1/warranty-tracker` — the fields this
 * page reads. A working shape, not a copy of an OpenAPI schema. `make new-module`
 * already put the module's endpoints into `api-generated.ts`; once this type is
 * the same as the generated schema, make it an alias of that schema instead.
 */
export interface WarrantyWidget {
  id: string;
  name: string;
  quantity: number;
}

/** One page of the list: the rows, how many there are, whether more follow. */
export interface WarrantyWidgetPage {
  items: WarrantyWidget[];
  total: number;
  has_more: boolean;
}
```

The query, in `warranty_tracker/hooks/useWidgets.ts` — server state lives in
hooks, not in components:

```ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/module-sdk";
import type { WarrantyWidgetPage } from "../types";

export function useWidgets() {
  return useQuery({
    queryKey: ["warranty_tracker", "widgets"],
    queryFn: () =>
      api.get<WarrantyWidgetPage>("/warranty-tracker").then((r) => r.data),
  });
}
```

The page, in `warranty_tracker/pages/IndexPage.tsx`. The shell draws the title
from `setHeader`; `QueryResult` covers loading and failure, `EmptyState` the
empty list:

```tsx
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Package } from "lucide-react";
import {
  Card,
  CardContent,
  EmptyState,
  QueryResult,
  useModulePageHeader,
} from "@/module-sdk";
import { useWidgets } from "../hooks/useWidgets";

export default function IndexPage() {
  const { t } = useTranslation("warranty_tracker");
  const { setHeader } = useModulePageHeader();
  const widgets = useWidgets();

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("description") });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <QueryResult query={widgets}>
        {({ items }) =>
          items.length === 0 ? (
            <EmptyState
              icon={Package}
              title={t("empty")}
              description={t("emptyHint")}
            />
          ) : (
            <Card>
              <CardContent className="divide-y divide-border">
                {items.map((widget) => (
                  <div key={widget.id} className="flex justify-between py-2">
                    <span className="text-on">{widget.name}</span>
                    <span className="text-on-secondary">{widget.quantity}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )
        }
      </QueryResult>
    </div>
  );
}
```

Open http://localhost:5173/warranty-tracker. Empty, it says *Nothing here
yet.* Create a widget with `POST /api/v1/warranty-tracker` in the API docs,
reload, and it is on the list — the module working end to end.

> **Rules**: import Core only from `@/module-sdk` — `<Card>`, `<Button>`,
> `<Input>`, the registry, `api`, `extractApiError` for a failed request's
> message. No hard-coded user-visible text — `t('key')`.

---

### 5. Add translations

The scaffold already wrote `frontend/src/modules/warranty_tracker/i18n/en.json`
and the matching `pl`, `de`, `fr`, `es` files with placeholders. A module built
into this repository owes all five, so fill all five. (A package you distribute,
Path B below, owes English only: a reader in a language it does not ship sees it
in English, key by key.) The page above reads two keys the scaffold did not
write, `empty` and `emptyHint`; add them to every file.

Edit `frontend/src/modules/warranty_tracker/i18n/en.json`:

```json
{
  "title": "Warranty Tracker",
  "description": "Track product warranties.",
  "navigation": { "title": "Warranties" },
  "permissions": {
    "read": "View warranties",
    "readDesc": "Can open the warranty list",
    "write": "Manage warranties",
    "writeDesc": "Can add, edit and remove warranties"
  },
  "empty": "Nothing here yet.",
  "emptyHint": "Add the first one and it will show up here."
}
```

`title` and `description` are the page header, `navigation.title` the label
of the module's nav entry in `module.ts`, `permissions` the names the role
editor shows for the two permissions the manifest declares, and `empty` and
`emptyHint` the empty list (a page's empty state needs a description).

---

### 6. Write the purpose card

Create `docs/purpose/<module>.md` — seven short headings saying whose job the module serves, where
it ends, and what it deliberately does **not** do. The shape and the rules are in
[`docs/purpose/README.md`](docs/purpose/README.md); `make lint` fails for a module without one.

It takes ten minutes and it is the only place the boundary is written down. Everything else — the
manifest description, the i18n title — says what the module *can do*, which is why a review with
nothing but those grades each field on whether it is labelled, and never asks whether the field
belongs to the person doing the job.

---

### 7. Check it

```bash
make validate-module      # manifests and import rules
make lint                # the full lint: purpose cards, dead code, doc paths (the commit hook does not run these)
docker compose exec backend uv run pytest -n 4 -q app/modules/warranty_tracker
docker compose exec -T frontend npx tsc --noEmit
```

The commit hook checks the rest on every commit — ruff, the architecture
lint, prettier, eslint, the catalog snapshot — and a scaffold made by
`make new-module` passes all of them as generated.

`make check-frontend` stops at the checks it is there to stop at. The
scaffold itself trips one of them: every API route needs a caller in the UI or
a recorded reason. (A second is every page's empty state needing a description,
which the page above has.) The scaffold's router answers `GET`/`POST /api/v1/warranty-tracker`
and `GET`/`PATCH`/`DELETE /api/v1/warranty-tracker/{widget_id}`; the page in
step 4 calls the first. Wire the others into the screens that need them,
delete the routes the module does not need, or record an API-only route in
`frontend/scripts/integration-only.json` with a reason, an owner and an
expiry. Before the push comes the
full gate in [CONTRIBUTING.md](CONTRIBUTING.md) (*Making Changes*): the backend
suite with its coverage floors, the type check and the frontend tests.

---

### 8. Submit

```bash
git add backend/app/modules/warranty_tracker frontend/src/modules/warranty_tracker \
        backend/app/core/module_safety.py frontend/scripts/module-catalog.json \
        frontend/scripts/i18n-backend-keys.json docs/api/openapi.json \
        frontend/src/types/api-generated.ts frontend/src/types/api-routes.ts \
        docs/purpose/warranty_tracker.md
git commit -m "Add the warranty tracker module"
git push -u origin feature/warranty-tracker
# open a GitHub issue first if there is none, then a pull request against dev that
# references it (sign the CLA on your first pull request; see CONTRIBUTING.md)
```

---

## Path B: Community module package (for distribution)

### 1. Scaffold the package

<!-- quickstart-check: scaffold -->

```bash
docker compose exec backend uv run python manage.py module new-community \
  warranty_tracker --output /modules-workspace
```

This is the non-interactive equivalent of
`make new-community-module NAME=warranty_tracker` and creates
`./modules-workspace/warranty_tracker/` on the host.

`modules-workspace/` is yours: git ignores its contents, so this repository
cannot swallow your module, and it is mounted into the backend container, so
the installer below can reach the package without it having to sit inside
Inventari's own source tree.

This creates a **standalone directory** containing both layers:

```
warranty_tracker/
├── module.yaml          ← unified manifest (version, author, requires)
├── README.md
├── backend/             ← FastAPI module
└── frontend/            ← React module
```

The package ships a home-screen tile (a `launcher` entry in the frontend half's `module.ts`), a catalog
in English on both halves (English is the only language a package must ship; add
`-l pl -l de` for more of the five), a `Record` model with the migration that creates its
table, and a placeholder `/items/{id}` endpoint
that raises a translated 404: its message is read from `backend/i18n/<lang>.json`, whose
keys sit at the top level of the file (a message nested under `errors` is never found).

`module.yaml` carries two numbers: `version` is your module's own, and
`inventari_min_version` is the oldest platform it is known to run on — a floor
above the running platform refuses the install. See
[docs/MODULE_VERSIONING.md](docs/MODULE_VERSIONING.md).

### 2. Develop normally

The package is smaller than Path A's scaffold, so Path A's steps 2 to 4 do not
apply to it as written: it is not a copy of `example_widgets`. What it holds:

- `GET /api/v1/warranty-tracker/hello`, and `GET /api/v1/warranty-tracker/items/{item_id}`,
  a placeholder that always answers a translated 404;
- a `Record` model and the migration that creates its table;
- a placeholder page that hands the module's title to the shell through
  `useModulePageHeader()` and shows nothing below it.

It has **no list endpoint**: until you add one, `GET /api/v1/warranty-tracker`
answers 404. The rules of Path A step 2 hold here too — the router is guarded by
`require_module('warranty_tracker')`, your own tables you query directly, Core
data only through `core_api`.

#### A list of your records

Make the package answer the way Path A's does: a list endpoint over `Record`,
and a page that shows it. Each block names the file it goes into and how: the
imports go to the top of the package's `router.py`, the endpoint to its end;
the backend files are in the backend half of the package, the frontend ones in its frontend half.

<!-- quickstart-package: backend/schemas.py replace -->

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecordSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
```

<!-- quickstart-package: backend/router.py prepend -->

```python
from uuid import UUID

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import PaginatedResponse, get_async_db, require_org

from .models import Record
from .schemas import RecordSchema
```

<!-- quickstart-package: backend/router.py append -->

```python
@router.get("", response_model=PaginatedResponse[RecordSchema])
async def list_records(
    db: AsyncSession = Depends(get_async_db, scope="function"),
    org_id: UUID = Depends(require_org),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[RecordSchema]:
    """The organization's records, newest first — filtered by organization, always."""
    mine = Record.organization_id == org_id
    total = await db.scalar(select(func.count()).select_from(Record).where(mine))
    rows = await db.scalars(
        select(Record)
        .where(mine)
        .order_by(Record.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return PaginatedResponse[RecordSchema].from_slice(
        [RecordSchema.model_validate(row) for row in rows], offset, limit, total or 0
    )
```

Once the module is installed and on (the end of this step), `GET /api/v1/warranty-tracker`
answers an empty page:
`{"items": [], "total": 0, "limit": 100, "offset": 0, "has_more": false, "total_capped": false}`.

The screen. The shell draws the title from `setHeader`; `QueryResult` covers
loading and failure, `EmptyState` the empty list. The placeholder page is
replaced whole.

<!-- quickstart-package: frontend/types/index.ts replace -->

```ts
/** One row of `GET /api/v1/warranty-tracker` — the fields the page reads. */
export interface WarrantyRecord {
  id: string;
  created_at: string;
}

/** One page of the list: the rows, how many there are, whether more follow. */
export interface WarrantyRecordPage {
  items: WarrantyRecord[];
  total: number;
  has_more: boolean;
}
```

<!-- quickstart-package: frontend/hooks/useRecords.ts replace -->

```ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/module-sdk";
import type { WarrantyRecordPage } from "../types";

export function useRecords() {
  return useQuery({
    queryKey: ["warranty_tracker", "records"],
    queryFn: () =>
      api.get<WarrantyRecordPage>("/warranty-tracker").then((r) => r.data),
  });
}
```

<!-- quickstart-package: frontend/pages/IndexPage.tsx replace -->

```tsx
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Package } from "lucide-react";
import {
  Card,
  CardContent,
  EmptyState,
  QueryResult,
  useModulePageHeader,
} from "@/module-sdk";
import { useRecords } from "../hooks/useRecords";

export default function IndexPage() {
  const { t, i18n } = useTranslation("warranty_tracker");
  const { setHeader } = useModulePageHeader();
  const records = useRecords();

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("description") });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <QueryResult query={records}>
        {({ items }) =>
          items.length === 0 ? (
            <EmptyState icon={Package} title={t("empty")} />
          ) : (
            <Card>
              <CardContent className="divide-y divide-border">
                {items.map((record) => (
                  <div key={record.id} className="py-2 text-on">
                    {new Date(record.created_at).toLocaleString(i18n.language)}
                  </div>
                ))}
              </CardContent>
            </Card>
          )
        }
      </QueryResult>
    </div>
  );
}
```

The page reads one key the package did not write, `empty`. Add it to
the package's English catalog (`en.json`, in the `i18n` directory of its frontend half),
beside the keys that are there:

<!-- quickstart-package: frontend/i18n/en.json merge -->

```json
{ "empty": "Nothing here yet." }
```

#### Your module's own tables

The scaffold ships a model and the migration that creates its table; rename
`Record` in your package's `models.py` to what your module keeps. Rename every
other use of that name with it: the `from .models import Record` import and the
queries in `router.py` (the list endpoint above reads `Record`), the import in
the test the scaffold ships (`test_records.py`), and the table name in
`backend/migrations/versions/001_initial.py`. The model inherits
`ModuleModelBase` — the declarative base the contract surface exports, and the
one this guide and the scaffold use:

```python
from sqlalchemy.orm import Mapped, mapped_column

from app.core.contracts import ModuleModelBase


class Warranty(ModuleModelBase):
    __tablename__ = 'warranty_tracker_warranties'

    id: Mapped[int] = mapped_column(primary_key=True)
```

A column that points at a core table — the scaffold's `organization_id` is one
— declares no `ForeignKey` on the model: `ModuleModelBase`'s metadata holds the
module's tables only, so `ForeignKey('organizations.id')` cannot resolve its
target and the first flush raises `NoReferencedTableError`. The module's
migration declares the constraint instead; the database still enforces it, and
the core's metadata never learns about the module's tables.

The core's `Base` is not an option for a community module: its metadata is
Core's, so a table declared on it would be proposed by Core's autogenerate and
created by a core migration — against the ownership rule below. The SDK's
`CoreModelBase` is the same base, for the modules this repository ships.
`ModuleModelBase` has a metadata of its own, so the platform's
autogenerate never proposes your tables and no core migration creates them —
your chain under `backend/migrations/` does, and `manage.py db upgrade-modules`
applies it at startup, the first time on the startup after the install;
enabling the module for an organization runs no migration. Every later change
to `models.py` gets a revision beside the first, its `down_revision` naming the
revision before it; MODULES_GUIDE.md → *Database Migrations* has the details.

Your package's own tests live in the package (`backend/tests/`) and never
install — no installed copy of the module carries them. Run them, and the
frontend type check, from your package repository against a checkout with the
sequence in [docs/MODULE_TESTING_GUIDE.md](docs/MODULE_TESTING_GUIDE.md)
(*Running a community package's tests*): the backend stops, both halves are
staged into the checkout for the length of the run, and afterwards the tree —
an installed copy of the same module and the development database included —
is as it was.

Then test by installing locally:

Either sign the package with a key the installation trusts (the default path,
and the one a published module needs):

<!-- quickstart-check: keygen -->

```bash
# 1. One-time: generate an Ed25519 keypair (writes the private key to
#    modules-workspace/my-ed25519.key on the host, prints the public one).
#    Run it once: if that file exists the command stops and leaves it alone.
docker compose exec backend uv run python -c "
import base64, os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
k = Ed25519PrivateKey.generate()
fd = os.open('/modules-workspace/my-ed25519.key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.fchmod(fd, 0o600)
os.write(fd, base64.b64encode(k.private_bytes(
    serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
)))
os.close(fd)
print('public key:', base64.b64encode(k.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)).decode())
"
```

Then trust that key and use it:

```bash
# 2. One-time: trust that key. Put MODULE_SIGNING_PUBLIC_KEYS=my-releases=<base64 public key>
#    in .env, then recreate the backend — a restart keeps the old environment.
docker compose up -d backend

# 3. Sign the package (again after every content change), then install it
docker compose exec backend uv run python manage.py module sign \
  /modules-workspace/warranty_tracker --key /modules-workspace/my-ed25519.key --key-id my-releases
docker compose exec backend uv run python manage.py module install /modules-workspace/warranty_tracker

docker compose restart backend
docker compose restart frontend
```

The installer prints these two lines itself, for the stack it ran on; on a
production stack the frontend line is a rebuild of its image instead.

Or, for local development without key handling, install the package unsigned,
deliberately — and do not sign it first. A package that carries a `module.sig`
is always verified, and `--allow-unsigned` does not apply to it:

<!-- quickstart-check: install -->

```bash
docker compose exec backend uv run python manage.py module install \
  /modules-workspace/warranty_tracker --allow-unsigned
```

The installer refuses an unsigned package by default — module code runs
in-process with full access to the database and the filesystem, so an install
is a trust decision: signed by a key the installation lists, or taken
deliberately with `--allow-unsigned`.

Run a smoke check of the installed backend's manifest, import safety and
translations — and that the package imports at all — before restarting the
services:

<!-- quickstart-check: smoke -->

```bash
docker compose exec backend uv run python manage.py module validate \
  --module warranty_tracker
```

Then restart the backend and rebuild/restart the frontend as in the signed
path above. The scaffold's `/hello` endpoint is guarded by module activation;
activate **Warranty Tracker** in **Settings → Modules** before using it. Then
`GET /api/v1/warranty-tracker` answers the empty page shown above, and
http://localhost:5173/warranty-tracker says *Nothing here yet.* under the module's
title.

After the first install, `module install` refuses the same module again
("already installed"), and `module upgrade` refuses a package whose version is
the one already installed. To try an edit, upgrade from the same directory with
`--force`, which takes the package although its version has not moved — the
module's rows are kept — then restart as above:

```bash
docker compose exec backend uv run python manage.py module upgrade \
  /modules-workspace/warranty_tracker --allow-unsigned --force
```

That is the unsigned loop. A package that carries a `module.sig` no longer
matches it after an edit and is refused: sign it again (step 3 of the signed
path) and leave out `--allow-unsigned`.

The backend test suite executes the marked scaffold, key-generation, unsigned
install and smoke-check commands above in order, using temporary install
directories. Keep the markers with their commands: the pre-push gate checks
this local development path directly from this document. The guide shows the
same key-generation command, and the suite checks that the two stay identical.

### 3. Publish

Push your directory to a public GitHub repository:

```bash
cd modules-workspace/warranty_tracker
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/yourname/inventari-module-warranty-tracker.git
git push -u origin main
git tag v0.1.0 && git push origin v0.1.0
```

Commit the `module.sig` your signing step wrote, so the published revision is
the signed one. Users install it with:

```bash
docker compose exec backend uv run python manage.py module install \
  https://github.com/yourname/inventari-module-warranty-tracker.git --rev v0.1.0
```

Your key has to be in their `MODULE_SIGNING_PUBLIC_KEYS` for that to verify,
listed under the same key id you gave `module sign --key-id` (`my-releases`
above). The id is written into `module.sig`; an installation that lists the key
under another id refuses the package with "signing key 'my-releases' is not
trusted". An unsigned package is refused unless they pass `--allow-unsigned` deliberately; a
package whose signature does not verify — tampered content, or a key they do
not trust — has no switch at all.

### 4. Ship a new version

```bash
docker compose exec backend uv run python manage.py module upgrade \
  https://github.com/yourname/inventari-module-warranty-tracker.git --rev v0.2.0
docker compose restart backend && docker compose restart frontend
```

Replaces the files, runs your migrations, keeps every row your module stored.
Your `on_upgrade(old_version, context)` hook — declare it with
`define_module(on_upgrade_hook=...)` — runs on that restart.

### 5. Uninstall

```bash
docker compose exec backend uv run python manage.py module uninstall warranty_tracker
docker compose restart backend && docker compose restart frontend
```

The module's data is kept, and the command prints what it leaves behind before
asking. To drop the module's tables as well — for every organization on the
installation — add `--drop-data` and confirm by typing the word `data`.

### 6. When the backend does not come back

The installer and `module validate` import your package and refuse one that
does not, and the backend starts without a module it rejects, naming it and
the reason in its log and in `module list`. If the backend still restarts in
a loop after you installed or upgraded a module, `docker compose exec` has no
running container to enter; uninstall from a one-off one instead:

```bash
docker compose logs --tail 80 backend
docker compose run --rm --no-deps -T --entrypoint uv backend \
  run python manage.py module uninstall warranty_tracker
docker compose restart backend
```

Your data is kept. [MODULES_GUIDE.md](MODULES_GUIDE.md#when-the-backend-does-not-come-back)
has the production form of the command.

---

## Reference examples

| Module | Good for learning |
|---|---|
| `example_widgets` | The reference module the scaffold copies — start here |
| `shopping_lists` | A full CRUD module with automatic suggestions; it requires `items` and `categories` |
| `stats` | Analytics, read-only queries |
| `webhooks` | External integrations, event-driven |
| `printing` | File generation, external services |

→ Full architecture + community module guide: [MODULES_GUIDE.md](MODULES_GUIDE.md)  
→ UI patterns: [frontend/UI_GUIDELINES.md](frontend/UI_GUIDELINES.md)  
→ Testing guide: [backend/tests/README.md](backend/tests/README.md)
