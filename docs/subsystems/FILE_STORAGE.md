# File Storage Service

- **Location**: `backend/app/core/file_storage/` (Core service, not a module)
- **Service**: `FileStorageService` (Singleton facade)
- **Module-facing API**: `core_api.file_storage` (`backend/app/core/public_api/file_storage.py`)

## Supported Backends
1. **Local**: Filesystem storage (default).
2. **S3-Compatible**: AWS S3, Cloudflare R2, OVH Object Storage.

## Configuration (.env)
```
FILE_STORAGE_BACKEND=local|s3
FILE_STORAGE_LOCAL_PATH=/app/uploads
FILE_STORAGE_S3_BUCKET=...
FILE_STORAGE_S3_ACCESS_KEY=...
FILE_STORAGE_S3_SECRET_KEY=...
FILE_STORAGE_S3_REGION=us-east-1
FILE_STORAGE_S3_ENDPOINT_URL=...
```

## The key scheme — a contract for backup, restore and migration

Every file has one **storage key**, and the database stores the key, never the
address a backend builds for it. A key is:

```
<organization_id>/<module>/<relative>
```

- `<organization_id>` — the organization UUID, always the first segment.
- `<module>` — the module that owns the family of files (`items`, `recipes`,
  `equipment`, `attachments`, `organizations`). Core-owned families use the
  Core name they already had.
- `<relative>` — the leaf below, chosen by the owner.

`core_api.file_storage.save_for_org_async(org, module, relative, ...)` builds the
prefix itself and returns the full key. The facade rebuilds the prefix on
every read, so a relative path can never be read outside its
`<org>/<module>/` namespace.

### Leaf names

| Family | Key | Written by |
|---|---|---|
| Item cover | `<org>/items/<item_id>/cover.<ext>` | `POST /items/{id}/image` (`backend/app/api/_items_images.py`) |
| Recipe cover | `<org>/recipes/<recipe_id>/cover.<ext>` | recipe cover upload and import (`backend/app/modules/recipes/_recipe_cover.py`) |
| Item attachment | `<org>/attachments/<item_id>/<uuid>.<ext>` | `backend/app/services/attachment_service.py` |
| Equipment attachment | `<org>/equipment/<item_id>/<uuid>.<ext>` | `backend/app/modules/equipment/attachment_service.py` |
| Organization logo | `<org>/organizations/logo.<ext>` | `POST /organizations/logo` (`backend/app/api/organizations.py`) |

`<ext>` is derived from the validated content type, never from the client's
filename: `jpg`, `png`, `gif` or `webp` for the image families, the accepted
extension for an attachment. A file is overwritten in place under the same key
(no versions, no appends).

### What the columns hold

- `items.image_url`, `product_templates.image_url` and `recipes.image_url`
  hold the storage key above — or an absolute `http(s)` address for a picture
  that genuinely lives on another server (a product photo copied from a
  catalogue). The address a client loads is built when the row is read:
  a key becomes `/uploads/<key>`, a foreign address is returned unchanged
  (`backend/app/core/file_reference.py`, plus the `image_url` property on each model).
  The column keeps its historical name; what it holds is a reference.
- `organizations.logo_url` holds the key; the settings screen builds
  `/uploads/<key>` from it and the PDF service reads the bytes server-side.
- `item_attachments.file_path` holds the full key;
  `equipment_attachments.file_path` holds the relative part
  (`<item_id>/<uuid>.<ext>`) and the facade rebuilds the prefix.

### The rule for a module's own files

1. Save through `core_api.file_storage.save_for_org_async` with your module's name
   as `<module>` and a leaf under the entity it belongs to
   (`<entity_id>/<name>.<ext>`); keep the **returned key** on your row.
2. Never store the value `get_url_for_org_async` (or any backend method) returns.
   Build the address on read instead: keys served by the app go through
   `/uploads/<key>` — `served_url` in `backend/app/core/file_reference.py`,
   re-exported by `app.core.module_sdk` for module code — and a row's reader
   decides how it wants it. Backend switch = configuration; no row changes.
3. Register an `UploadPathResolver` (`backend/app/core/contributions.py`) that verifies
   ownership of the key, or the file is not served at all — `/uploads/` is
   authenticated and each family resolves its own paths.

## Serving

`GET /uploads/{key}` (`backend/app/api/uploads.py`) verifies that the caller's
organization owns the file, then reads the bytes through `FileStorageService`.
The route is the same for every backend: the local provider reads the file
from disk, S3 reads the object, and the address is identical in both cases.

## Switching backend or moving the bucket

The backend is configuration, not a data migration:

1. Copy the file tree so the keys are preserved — local
   `FILE_STORAGE_LOCAL_PATH/<key>` to bucket object `<key>`, or the reverse.
2. Change `FILE_STORAGE_BACKEND` and its settings, restart the API.
3. Nothing in the database changes; the same rows serve the same images.

The one migration that did touch rows was `imgkey01` (Core) and
`011_image_url_keeps_the_key` (Recipes): they rewrote image columns written by
builds that stored the address instead of the key. `imgkey01` belongs to the
pre-release core chain kept in `backend/migrations/versions_archive/`; a
database from that chain has to be at its end (past `imgkey01`) before it is
stamped onto the baseline, so nothing re-runs it. `011_image_url_keeps_the_key`
runs with the Recipes module chain. Neither needs an operator step.

## Security
- Path traversal protection.
- No versions kept: saving to an existing path overwrites the file. A cover
  therefore never reuses a name for a different picture: it is saved as
  `cover.<digest of the bytes>.<ext>` (`cover_leaf`), so a replaced picture is a
  new address and the old file is deleted once the row names the new one.
- Every `/uploads/` read is organization-scoped by an `UploadPathResolver`.
- A delete never follows the stored reference: it reads only the cover's file name and
  rebuilds the key from the organization and the entity it is serving
  (`cover_leaf_of` in `backend/app/core/file_reference.py`). Those columns
  are writable through the forms, so a reference naming another row's picture
  must not be able to select the object that gets removed.
