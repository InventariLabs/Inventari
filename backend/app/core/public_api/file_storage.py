"""
CoreFileStorageAPI — module-safe access to the file storage backend.

Modules should use this instead of importing FileStorageService directly
so that the storage abstraction layer (local vs S3) is transparently applied.

Every method stores under an enforced ``<org>/<module>/`` prefix: the caller
hands in the organization, the family name and a relative path, and the prefix
is rebuilt on every call — a stored relative path can never be re-read outside
its namespace. The unscoped ``save``/``get``/``get_url``/``delete``/``exists``
methods this class offered before the org-scoped variants allowed any module
to reach any path; they were removed before the repository went public rather
than carried through a deprecation window nobody existed to read.
"""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

# FileStorageService uses __new__-based singleton; calling FileStorageService()
# in each method is safe and always returns the same initialised instance.
from app.core.demo_upload_cap import demo_upload_admission
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger

logger = get_logger(__name__)


class CoreFileStorageAPI:
    """Public Core API for modules to use the configured file storage."""

    @staticmethod
    def _scoped_path(organization_id: UUID, module_name: str, file_path: str) -> str:
        """Build an org+module-scoped path: ``<org>/<module>/<file_path>``.

        Strips any leading ``/`` from *file_path* so the prefix is always
        enforced regardless of caller input.
        """
        clean = file_path.lstrip('/')
        return f'{organization_id}/{module_name}/{clean}'

    async def save_for_org_async(
        self,
        organization_id: UUID,
        module_name: str,
        file_path: str,
        content: bytes,
        content_type: str = 'application/octet-stream',
    ) -> str:
        """Save *content* under an enforced ``<org>/<module>/`` prefix.

        Returns the full scoped path that was stored.
        """
        scoped = self._scoped_path(organization_id, module_name, file_path)
        service = FileStorageService()
        async with demo_upload_admission(len(content)):
            await service.save(scoped, BytesIO(content), content_type)
        return scoped

    async def get_for_org_async(
        self, organization_id: UUID, module_name: str, file_path: str
    ) -> bytes:
        """Retrieve a file previously saved via :meth:`save_for_org_async`."""
        scoped = self._scoped_path(organization_id, module_name, file_path)
        buf: BytesIO = await FileStorageService().get(scoped)
        return buf.read()

    async def get_url_for_org_async(
        self,
        organization_id: UUID,
        module_name: str,
        file_path: str,
        expires_in: int | None = None,
    ) -> str:
        """Get a URL for a file saved via :meth:`save_for_org_async`."""
        scoped = self._scoped_path(organization_id, module_name, file_path)
        return await FileStorageService().get_url(scoped, expires_in)

    async def delete_for_org_async(
        self, organization_id: UUID, module_name: str, file_path: str
    ) -> None:
        """Delete a file previously saved via :meth:`save_for_org_async`."""
        scoped = self._scoped_path(organization_id, module_name, file_path)
        await FileStorageService().delete(scoped)

    async def exists_for_org_async(
        self, organization_id: UUID, module_name: str, file_path: str
    ) -> bool:
        """Check whether a file saved via :meth:`save_for_org_async` exists."""
        scoped = self._scoped_path(organization_id, module_name, file_path)
        return await FileStorageService().exists(scoped)
