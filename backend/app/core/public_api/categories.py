"""
Module-safe access to categories (read and write).

Modules must not query ``Category`` directly — they should use this API to stay
within the public contract and benefit from future caching / permission checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    CategoryCreateDTO,
    CategoryDTO,
    CategoryUpdateDTO,
    UserContextDTO,
)
from app.core.logging import get_logger
from app.core.public_api._access import reads, writes
from app.services._category_reads import (
    count_items_per_category_async,
    existing_category_ids_async,
    get_by_id_async,
    get_categories_async,
    list_with_filters_async,
)
from app.services._category_writes import (
    create_category,
    delete_category,
    update_category,
)

if TYPE_CHECKING:
    from app.models.category import Category

logger = get_logger(__name__)


def _stamp_module_ownership(
    categories: list[Category], dtos: list[CategoryDTO]
) -> list[CategoryDTO]:
    """Set ``is_module_owned`` on each DTO from its category's context tag.

    The same registry read the list isolation applies — a category whose
    context tag a module claims files its records under that module whether
    or not the organisation has the module enabled, because the data outlives
    it. Read here, at the one place every category leaves the Core, so the
    flag cannot drift between the lists that isolate and the screens that
    speak.
    """
    from app.core.module_scope import get_claimed_context_tags

    claimed = get_claimed_context_tags()
    for category, dto in zip(categories, dtos, strict=True):
        dto.is_module_owned = category.context_tag in claimed
    return dtos


class CoreCategoriesAPI:
    """Public Core API for module-safe category reads and writes.

    Only active (``is_active=True``) categories are returned.  Modules may read
    both organisation-specific and system (``organization_id=None``) categories
    that are visible to the given organisation.
    """

    @reads
    async def list_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
    ) -> list[CategoryDTO]:
        """Return all active categories using an AsyncSession."""
        categories = await get_categories_async(db, organization_id)
        dtos = [CategoryDTO.model_validate(category) for category in categories]
        return _stamp_module_ownership(categories, dtos)

    @reads
    async def list_with_filters_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        include_inactive: bool = False,
        claimed_tags: set[str] | None = None,
        with_counts: bool = False,
    ) -> list[CategoryDTO]:
        """List categories visible to *organization_id* with optional filters.

        Includes system categories (``organization_id IS NULL``) and org-specific
        ones.  When *claimed_tags* is provided, categories whose
        ``context_tag`` is in that set are excluded (module-context isolation).
        Inactive categories are excluded by default.  With *with_counts*, each
        DTO carries how many live items are filed under it.
        """

        categories = await list_with_filters_async(
            db,
            organization_id,
            include_inactive=include_inactive,
            claimed_tags=claimed_tags,
        )
        dtos = [CategoryDTO.model_validate(c) for c in categories]
        _stamp_module_ownership(categories, dtos)
        if with_counts:
            counts = await count_items_per_category_async(db, organization_id)
            for dto in dtos:
                dto.items_count = counts.get(dto.id, 0)
        return dtos

    @reads
    async def get_by_id_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        category_id: UUID,
    ) -> CategoryDTO | None:
        """Return a single category visible to *organization_id*, or ``None``."""

        category = await get_by_id_async(db, organization_id, category_id)
        if not category:
            return None
        dto = CategoryDTO.model_validate(category)
        return _stamp_module_ownership([category], [dto])[0]

    @reads
    async def existing_ids_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        category_ids: set[UUID],
    ) -> set[UUID]:
        """Return the subset of *category_ids* visible to *organization_id* — one query.

        The write-layer twin of ``get_by_id_async``'s existence question,
        with its exact semantics (the organization's own plus the system
        catalogue): a door storing category references refuses unknown ids
        before the INSERT, and asks once for the whole batch instead of
        per line.
        """

        return await existing_category_ids_async(db, organization_id, category_ids)

    @writes
    async def create_async(
        self,
        db: AsyncSession,
        category_in: CategoryCreateDTO,
        user: UserContextDTO,
    ) -> CategoryDTO:
        """Create a new category. Returns the created CategoryDTO.

        Runs the full pipeline: interceptors, duplicate-name check, event.
        Raises ``ValueError`` on duplicate name.
        """
        from app.schemas.category import CategoryCreate

        internal = CategoryCreate(**category_in.model_dump())
        category = await create_category(db, internal, user)
        dto = CategoryDTO.model_validate(category)
        return _stamp_module_ownership([category], [dto])[0]

    @writes
    async def update_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        category_id: UUID,
        category_in: CategoryUpdateDTO,
        user: UserContextDTO,
    ) -> CategoryDTO | None:
        """Update a category by ID. Returns the updated CategoryDTO or ``None``."""

        category = await get_by_id_async(db, organization_id, category_id)
        if category is None:
            return None

        from app.schemas.category import CategoryUpdate

        internal = CategoryUpdate(**category_in.model_dump(exclude_unset=True))
        updated = await update_category(db, category, internal, user)
        if not updated:
            return None
        dto = CategoryDTO.model_validate(updated)
        return _stamp_module_ownership([updated], [dto])[0]

    @writes
    async def rename_group_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        current_name: str,
        new_name: str | None,
        category_ids: list[UUID] | None = None,
        user: UserContextDTO,
    ) -> list[UUID]:
        """Rename a category group, or take it off the categories that carry it.

        Returns the ids of the categories changed.
        """
        from app.services._category_writes import rename_category_group

        return await rename_category_group(
            db,
            organization_id=organization_id,
            user=user,
            current_name=current_name,
            new_name=new_name,
            category_ids=category_ids,
        )

    @writes
    async def delete_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        category_id: UUID,
        user: UserContextDTO,
    ) -> bool:
        """Delete a category by ID. Returns ``True`` if deleted, ``False`` if not found."""

        category = await get_by_id_async(db, organization_id, category_id)
        if category is None:
            return False
        await delete_category(db, category, user)
        return True
