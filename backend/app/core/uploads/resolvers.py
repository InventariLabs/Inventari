"""Core-owned upload path resolvers.

The single serving route ``GET /uploads/{filepath}`` verifies ownership before
serving any file. Each upload family (item cover, item attachment, recipe cover,
equipment attachment, …) records ownership differently, so resolution is
delegated to :class:`UploadPathResolver` contributions. This module holds the
two resolvers owned by Core; modules register their own via the
``upload_path_resolvers`` contribution point.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contributions import OwnedFileMeta, UploadPathResolver
from app.core.public_api import core_api

# file extension → MIME type, for cover images that have no DB content_type.
_EXT_TO_MIME: dict[str, str] = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'pdf': 'application/pdf',
}


class ItemCoverResolver(UploadPathResolver):
    """Resolve ``<org_id>/items/<item_id>/cover.<ext>`` — the item cover image.

    Cover uploads (_items_images.py) write the file and set ``item.image_url``
    but never create an attachment row, so ownership is verified by loading the
    item itself (``core_api.items.get_any_async`` is already org-scoped). The
    read reaches archived records too: an archive is a soft delete, the record
    keeps its cover, and its card still renders it. Removing the cover stays
    live-only on its own route. The
    ``<org>`` segment is checked hard: a path that does not name the asking
    organization as its first segment is never resolved here, whatever the
    rest of it looks like.

    A cover URL stored before the org-scoped move lacks that segment
    (``items/<item_id>/cover.<ext>``) and is deliberately unresolved: the
    record is not migrated — dev/demo stores reset with their stacks — so
    the screen shows no cover rather than this route reaching for a path
    outside the caller's namespace.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        parts = file_path.split('/')
        # Expected shape: <org_id>/items/<item_id>/cover.<ext>
        if len(parts) != 4 or parts[0] != str(organization_id) or parts[1] != 'items':
            return None
        try:
            item_id = UUID(parts[2])
        except ValueError:
            return None
        filename = parts[3]
        if not filename.startswith('cover.'):
            return None

        item = await core_api.items.get_any_async(db, organization_id, item_id)
        if item is None:
            return None

        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        return OwnedFileMeta(
            content_type=_EXT_TO_MIME.get(ext, 'application/octet-stream'),
            display_name=filename,
        )


class AttachmentResolver(UploadPathResolver):
    """Resolve ``<org_id>/attachments/{item_id}/{file}`` — files tracked in
    ``item_attachments``.

    The organization segment is the storage layer's own prefix
    (``save_for_org_async``) and is checked before anything is looked up; the row
    is then found by its file_path, org-filtered through the item's storage
    location, which is where the type and the display name come from.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        parts = file_path.split('/')
        if (
            len(parts) != 4
            or parts[0] != str(organization_id)
            or parts[1] != 'attachments'
        ):
            return None
        attachment = await core_api.attachments.find_by_file_path_async(
            db, file_path, organization_id=organization_id
        )
        if attachment is None:
            return None
        # file_type stores the MIME type on the core attachment model.
        return OwnedFileMeta(
            content_type=attachment.file_type,
            display_name=attachment.file_name,
        )


class OrganizationLogoResolver(UploadPathResolver):
    """Resolve ``<org_id>/organizations/logo.<ext>`` — the organization logo.

       The path is org-prefixed by the storage layer itself (``save_for_org_async``),
       so ownership is verified by loading the organization (``get_async`` is
       already org-scoped). Without this resolver the logo could not be served
    back to the settings UI.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        # Expected shape: <org_id>/organizations/logo.<ext>
        parts = file_path.split('/')
        if (
            len(parts) != 3
            or parts[0] != str(organization_id)
            or parts[1] != 'organizations'
        ):
            return None
        filename = parts[2]
        if not filename.startswith('logo.'):
            return None

        org = await core_api.organizations.get_async(db, organization_id)
        if org is None:
            return None

        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        return OwnedFileMeta(
            content_type=_EXT_TO_MIME.get(ext, 'application/octet-stream'),
            display_name=filename,
        )


# Ordered: core resolvers consulted first, then any module contributions.
CORE_RESOLVERS: list[UploadPathResolver] = [
    ItemCoverResolver(),
    AttachmentResolver(),
    OrganizationLogoResolver(),
]
