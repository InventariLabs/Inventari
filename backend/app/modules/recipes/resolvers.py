"""Recipes module upload path resolver.

Registers an :class:`UploadPathResolver` so the core ``/uploads/{path}``
serving route can verify ownership of recipe cover images, which are recorded
only on ``Recipe.image_url`` (no attachment row).
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contributions import OwnedFileMeta, UploadPathResolver

from ._crud import get_recipe

_EXT_TO_MIME: dict[str, str] = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
}


class RecipeCoverResolver(UploadPathResolver):
    """Resolve ``<org_id>/recipes/<recipe_id>/cover.<ext>`` — the recipe cover
    image.

    Ownership is verified by loading the recipe org-scoped via ``get_recipe``.
    The ``<org>`` segment is checked hard: a path whose first segment is not
    the asking organization's id is never resolved here.

    A cover URL stored before the org-scoped move lacks that segment
    (``recipes/<recipe_id>/cover.<ext>``) and is deliberately unresolved: the
    record is not migrated — development and demo stores are reset — so the
    screen shows no cover rather than this route reaching for a path outside
    the caller's namespace.
    """

    async def resolve(
        self,
        db: AsyncSession,
        file_path: str,
        organization_id: UUID,
    ) -> OwnedFileMeta | None:
        parts = file_path.split('/')
        # Expected shape: <org_id>/recipes/<recipe_id>/cover.<ext>
        if len(parts) != 4 or parts[0] != str(organization_id) or parts[1] != 'recipes':
            return None
        try:
            recipe_id = UUID(parts[2])
        except ValueError:
            return None
        filename = parts[3]
        if not filename.startswith('cover.'):
            return None

        recipe = await get_recipe(db, recipe_id, organization_id)
        if recipe is None:
            return None

        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        return OwnedFileMeta(
            content_type=_EXT_TO_MIME.get(ext, 'application/octet-stream'),
            display_name=filename,
        )
