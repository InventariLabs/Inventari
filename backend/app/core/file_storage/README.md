# File Storage Service

Centralized file storage abstraction layer supporting local disk and cloud providers (AWS S3, Cloudflare R2, OVH Object Storage).

## Quick Start

```python
from app.core.file_storage.service import FileStorageService
from app.core.file_storage.schemas import StorageConfigSchema
import io

# 1. Initialize the service once at app startup (`app/main.py` does it with
#    `FileStorageService.initialize_from_settings()`, which reads the
#    FILE_STORAGE_* settings below). Without this, every method call raises
#    FileStorageConfigError.
FileStorageService.initialize(
    StorageConfigSchema(
        backend='local',
        local_path='/app/uploads',
    )
)

# 2. Get the singleton instance and use it.
storage = FileStorageService()

# Save a file — `file_content` must be a BytesIO (the providers seek(0) and
# read() from it).
file_obj = io.BytesIO(b'Hello World')

info = await storage.save(
    file_path='documents/report.pdf',
    file_content=file_obj,
    content_type='application/pdf',
)

# `FileInfo` is a dataclass with: path, size, created_at, content_type, etag
# (no `url` field — call `storage.get_url(...)` if you need a URL).
print(f'File saved: {info.path}')
print(f'Size: {info.size} bytes')

# Get a file
content = await storage.get('documents/report.pdf')
data = content.read()  # Read as bytes

# Check if file exists
exists = await storage.exists('documents/report.pdf')

# Get a URL — S3: pass `expires_in_seconds` for a signed URL, omit for public
# URL. Local: always returns `/uploads/<path>` (a route of the app, which
# checks the caller's organization; the reverse proxy forwards it).
url = await storage.get_url('documents/report.pdf')
signed_url = await storage.get_url(
    'documents/report.pdf',
    expires_in_seconds=3600,  # 1 hour, S3 signed URL only
)

# Delete a file
await storage.delete('documents/report.pdf')
```

## Configuration

### Environment Variables

Set in `.env`:

```bash
# Backend type: 'local' or 's3'
FILE_STORAGE_BACKEND=local

# For local backend
FILE_STORAGE_LOCAL_PATH=/app/uploads

# For S3 backend (AWS, R2, OVH)
FILE_STORAGE_S3_BUCKET=my-storage-bucket
FILE_STORAGE_S3_ACCESS_KEY=your-access-key
FILE_STORAGE_S3_SECRET_KEY=your-secret-key
FILE_STORAGE_S3_REGION=us-east-1
FILE_STORAGE_S3_ENDPOINT_URL=          # Leave empty for AWS, set for R2/OVH
```

### Provider Examples

#### Local (VPS filesystem)
```bash
FILE_STORAGE_BACKEND=local
FILE_STORAGE_LOCAL_PATH=/app/uploads
```

#### AWS S3
```bash
FILE_STORAGE_BACKEND=s3
FILE_STORAGE_S3_BUCKET=my-bucket
FILE_STORAGE_S3_ACCESS_KEY=AKIA...
FILE_STORAGE_S3_SECRET_KEY=...
FILE_STORAGE_S3_REGION=eu-west-1
FILE_STORAGE_S3_ENDPOINT_URL=          # Empty
```

#### Cloudflare R2
```bash
FILE_STORAGE_BACKEND=s3
FILE_STORAGE_S3_BUCKET=my-bucket
FILE_STORAGE_S3_ACCESS_KEY=...
FILE_STORAGE_S3_SECRET_KEY=...
FILE_STORAGE_S3_REGION=auto            # R2 uses 'auto'
FILE_STORAGE_S3_ENDPOINT_URL=https://abc123.r2.cloudflarestorage.com
```

#### OVH Object Storage
```bash
FILE_STORAGE_BACKEND=s3
FILE_STORAGE_S3_BUCKET=my-bucket
FILE_STORAGE_S3_ACCESS_KEY=...
FILE_STORAGE_S3_SECRET_KEY=...
FILE_STORAGE_S3_REGION=sbg             # or gra, bhs, etc.
FILE_STORAGE_S3_ENDPOINT_URL=https://s3.sbg.perf.cloud.ovh.net
```

## API Reference

### FileStorageService

The main singleton service for all file operations.

#### `save(file_path, file_content, content_type) → FileInfo`

Saves a file to storage.

**Parameters:**
- `file_path` (str): Path where to save the file (e.g., `uploads/2026/02/photo.webp`)
- `file_content` (`BytesIO`): File content. Must be a `BytesIO` — the providers call `seek(0)` and `read()` on it.
- `content_type` (str): MIME type (e.g., `image/webp`, `application/pdf`)

**Returns:** `FileInfo` (dataclass from `app/core/file_storage/providers/base.py`) with:
- `path`: Saved file path
- `size`: File size in bytes
- `created_at`: Timestamp
- `content_type`: MIME type
- `etag`: ETag value (or `None` for local backend)

> The returned `FileInfo` does **not** include a `url` field. Call
> `get_url(file_path)` separately to obtain a `/uploads/` URL (local) or a
> public or signed URL (S3). A separate `FileInfoSchema` Pydantic model exists for API
> responses and does include `url`, but `save()` returns the dataclass.

**Example:**
```python
import io
from PIL import Image

# Create a WebP image
img = Image.new('RGB', (800, 600), color='red')
buffer = io.BytesIO()
img.save(buffer, format='WEBP')
buffer.seek(0)

info = await storage.save('images/product-123.webp', buffer, 'image/webp')
```

#### `get(file_path) → BytesIO`

Retrieves a file from storage.

**Parameters:**
- `file_path` (str): Path to the file

**Returns:** `BytesIO` object containing file content

**Raises:** `StoredFileNotFoundError` if the file is missing — a `StorageError` and a built-in `FileNotFoundError` at once, so either handler catches it

**Example:**
```python
content = await storage.get('images/product-123.webp')
image_bytes = content.read()
```

#### `get_url(file_path, expires_in_seconds=None) → str`

Generates a URL to access the file.

**Parameters:**
- `file_path` (str): Path to the file
- `expires_in_seconds` (int, optional): S3 only — generates a signed URL valid for this many seconds. **No default TTL**: if omitted, S3 returns a public URL (no signing). Local backend ignores this argument.

**Returns:** URL string

**Notes:**
- Local backend: Always returns `/uploads/<path>` (a relative URL; the app's own `GET /uploads/{key}` route serves it after an organization ownership check, and the reverse proxy forwards it there)
- S3 backend with `expires_in_seconds` set: signed URL with the given expiration
- S3 backend with `expires_in_seconds=None`: public bucket URL (no signing): `{endpoint}/{bucket}/<path>` when an endpoint is configured, else `https://{bucket}.s3.{region}.amazonaws.com/<path>`
- **Do not store this value in a row.** A file-backed column keeps the storage
  key `save_for_org_async` returns; the address is built when the row is read —
  otherwise switching backends or moving a bucket rewrites the database. See
  `docs/subsystems/FILE_STORAGE.md`.

**Raises:** `FileNotFoundError` if the file is missing.

**Example:**
```python
# Local — relative URL
url = await storage.get_url('images/product-123.webp')
# → /uploads/images/product-123.webp

# S3 — public URL (no TTL)
url = await storage.get_url('images/product-123.webp')
# → https://mybucket.s3.us-east-1.amazonaws.com/images/product-123.webp

# S3 — signed URL (1 hour)
url = await storage.get_url('images/product-123.webp', expires_in_seconds=3600)
# → https://mybucket.s3.amazonaws.com/images/product-123.webp?X-Amz-Expires=3600&...
```

#### `exists(file_path) → bool`

Checks if a file exists.

**Parameters:**
- `file_path` (str): Path to the file

**Returns:** `True` if file exists, `False` otherwise

**Example:**
```python
if await storage.exists('documents/invoice.pdf'):
    content = await storage.get('documents/invoice.pdf')
```

#### `delete(file_path) → None`

Deletes a file from storage.

**Parameters:**
- `file_path` (str): Path to the file

**Raises:** `StoredFileNotFoundError` if the file is missing (local backend only: S3 `DeleteObject` succeeds for a missing key, so the S3 provider does not raise)

**Example:**
```python
await storage.delete('temp/old-file.txt')
```

#### `empty() → int`

Deletes **every object** the storage holds — on a versioned bucket, every
version of it and every delete marker, so an old version id opens nothing
afterwards — and returns how many entries went. A store that does not
implement the versions listing (Cloudflare R2 keeps no versions) is emptied
through its current-object listing instead, where its keys are everything it
holds. Object storage (`s3`) only: the local backend is emptied by the
guarded directory walk in `backend/app/cli/commands_demo.py`, which keeps
the mount point and refuses a path that is not an uploads directory. The
caller this exists for is the demo reset, whose promise is that nothing
survives it (`docs/DEMO.md`).

**Returns:** the number of versions and delete markers deleted (one per key
in a bucket whose versioning was never turned on)

**Raises:** `StorageError` if the store refuses any entry — the listing stops
there rather than listing the same versions again — and `FileStorageConfigError`
when the backend has no wholesale emptier.

**Example:**
```python
removed = await storage.empty()
```

## Security Features

### Path Traversal Protection

The local backend prevents directory traversal attacks:

```python
# This is blocked - can't escape base path
await storage.save('../../../etc/passwd', BytesIO(b'...'), 'text/plain')
# → Raises RuntimeError("Path traversal attempted: ...")

# Only paths within base directory are allowed
await storage.save(
    'documents/report.pdf', BytesIO(pdf_bytes), 'application/pdf'
)  # ✓ OK
```

### One Version Per File

Saving a file with the same path overwrites the previous version:

```python
await storage.save('document.txt', BytesIO(b'version 1'), 'text/plain')
await storage.save('document.txt', BytesIO(b'version 2'), 'text/plain')  # Overwrites

# Only version 2 exists, version 1 is gone
content = await storage.get('document.txt')
assert content.read() == b'version 2'
```

## Error Handling

The service throws the following exceptions (from
`app.core.file_storage.errors`):

| Exception | When raised |
|---|---|
| `StorageError` | Base class for all file-storage errors. Catch this for a generic handler. |
| `FileStorageConfigError` | `FileStorageService.initialize(...)` was never called, or the config is invalid (e.g. missing `local_path` / S3 credentials). |
| `StoredFileNotFoundError` | The requested file does not exist (`get`, `get_url`, and `delete` on the local backend). It subclasses both `StorageError` and the built-in `FileNotFoundError`, so `except FileNotFoundError` and `except StorageError` both catch it. |

```python
from app.core.file_storage.errors import (
    StorageError,
    FileStorageConfigError,
)

try:
    content = await storage.get('missing-file.pdf')
except FileNotFoundError as e:
    print(f'Not found: {e}')
except FileStorageConfigError as e:
    print(f'Service not initialized: {e}')
except StorageError as e:
    print(f'Storage error: {e}')
```

## Usage in API Endpoints

Here's a typical example in a FastAPI endpoint:

```python
import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.core.file_storage.service import FileStorageService

router = APIRouter()


@router.post('/upload')
async def upload_file(file: UploadFile = File(...)):
    storage = FileStorageService()

    # Read uploaded file (file_content must be BytesIO — wrap the bytes)
    content = io.BytesIO(await file.read())

    # Save to storage
    info = await storage.save(
        f'uploads/{file.filename}',
        content,
        file.content_type or 'application/octet-stream',
    )

    return {
        'filename': file.filename,
        'size': info.size,
        'path': info.path,
    }


@router.get('/file/{file_id}')
async def get_file(file_id: str):
    storage = FileStorageService()

    if not await storage.exists(f'uploads/{file_id}'):
        raise HTTPException(status_code=404)

    url = await storage.get_url(f'uploads/{file_id}')
    return {'url': url}
```

## Testing

Tests are in `backend/tests/integration/file_storage/test_file_storage_service.py`:

```bash
# Run file storage tests
docker compose exec backend uv run pytest tests/integration/file_storage -v

# Run all tests (including file storage)
docker compose exec backend uv run pytest -v
```

## Architecture

The service uses a **provider pattern** for extensibility:

```
FileStorageService (Singleton)
    ├── LocalStorageProvider (filesystem)
    └── S3StorageProvider (AWS/R2/OVH compatible)
```

You can add new providers by implementing the abstract `StorageProvider` interface. See `app/core/file_storage/providers/base.py` for the contract.

## Performance Considerations

- **Local backend**: Fastest for single-server setups, synchronous I/O via `asyncio.to_thread()`
- **S3 backend**: Best for distributed systems, fully async via `aioboto3`
- **S3 signed URL TTL**: There is **no default TTL** — pass `expires_in_seconds` explicitly when calling `get_url(...)`. If omitted, S3 returns a public (unsigned) URL.
- **File size**: The storage service enforces no limit of its own and there is no `FILE_STORAGE_MAX_SIZE` setting; each upload endpoint caps its own body (for example 10 MB for item attachments), and a demo instance also caps the total (`DEMO_UPLOAD_TOTAL_MB`)

## Future Enhancements

- [ ] Async thumbnail generation with Celery
- [ ] Multipart upload for large files
- [ ] Virus scanning integration
- [ ] CDN integration (CloudFront, Cloudflare)
- [ ] Automatic cleanup of orphaned files
