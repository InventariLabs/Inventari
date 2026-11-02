from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemDTO, StorageDTO


class CoreStoragesAPI:
    """Public Core API for module-safe location access."""

    def label_caption(self, storage: StorageDTO) -> str | None:
        """The text under the QR code of this location's label.

        What the label endpoint prints when nobody overrides it: the
        description (or the name) when the location's setting shows it,
        nothing otherwise.
        """
        from app.services.storage._labels import (
            label_shows_description,
            storage_label_caption,
        )

        return storage_label_caption(storage, label_shows_description(storage))

    async def get_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_id: UUID,
    ) -> StorageDTO | None:
        from app.services.storage._queries import get_storage_async

        storage = await get_storage_async(db, organization_id, storage_id)
        if storage is None:
            return None
        return StorageDTO.model_validate(storage)

    async def find_by_scanned_code_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        code: str,
    ) -> StorageDTO | None:
        """The location a scanned code names (its own code or its label's), or ``None``.

        Read-only: no scan is counted against the label.
        """
        from app.services.storage._queries import find_by_scanned_code_async

        loc = await find_by_scanned_code_async(db, organization_id, code)
        if loc is None:
            return None
        return StorageDTO.model_validate(loc)

    async def scannable_code_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_id: UUID,
    ) -> str | None:
        """The code that names *storage_id* when scanned — its own, or its label's."""
        from app.services.storage._queries import scannable_code_async

        return await scannable_code_async(db, organization_id, storage_id)

    async def find_by_context_tag_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        context_tag: str,
    ) -> StorageDTO | None:
        from app.services.storage._queries import find_by_context_tag_async

        loc = await find_by_context_tag_async(db, organization_id, context_tag)
        if loc is None:
            return None
        return StorageDTO.model_validate(loc)

    async def list_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        context_tag: str | None = None,
        usage: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[StorageDTO]:
        from app.services.storage._queries import list_storages_async

        storages = await list_storages_async(
            db,
            organization_id,
            context_tag=context_tag,
            usage=usage,
            limit=limit,
            offset=offset,
        )
        return [StorageDTO.model_validate(s) for s in storages]

    async def create_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        name: str,
        user_id: UUID,
        description: str | None = None,
        behavior_mode: str | None = None,
        context_tag: str | None = None,
        usage: str | None = None,
        parent_id: UUID | None = None,
    ) -> StorageDTO:
        """Create a storage location. Runs interceptors and emits events.

        ``parent_id`` places it inside another location of the same
        organization; the parent is validated the way the API's own create
        validates it.
        """
        from app.core.contracts import UserContextDTO
        from app.schemas.storage_location import StorageLocationCreate

        storage_in = StorageLocationCreate(
            name=name,
            description=description,
            behavior_mode=behavior_mode,
            context_tag=context_tag,
            usage=usage,
            parent_id=parent_id,
        )
        user = UserContextDTO(id=user_id, organization_id=organization_id)

        from app.services.storage._writes import create_storage

        storage = await create_storage(db=db, storage_in=storage_in, user=user)
        return StorageDTO.model_validate(storage)

    async def list_storage_ids_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[UUID]:
        """Return just the IDs of storage locations for *organization_id*."""
        from app.services.storage._queries import list_storage_ids_async

        return await list_storage_ids_async(db, organization_id)

    async def get_with_type_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_id: UUID,
    ) -> StorageDTO | None:
        """Return a storage location with eager-loaded storage_type, or ``None``."""
        from app.services.storage._queries import get_storage_with_type_async

        storage = await get_storage_with_type_async(db, organization_id, storage_id)
        return StorageDTO.model_validate(storage) if storage else None

    async def item_counts_by_location_async(
        self, db: AsyncSession, organization_id: UUID, storage_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Return {storage_id: count} for non-deleted items in those storages."""
        from app.services.storage._queries import item_counts_by_location_async

        return await item_counts_by_location_async(db, organization_id, storage_ids)

    async def list_items_in_location_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_id: UUID,
        *,
        include_inside: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ItemDTO]:
        """List non-deleted items in *storage_id* ordered by expiry ascending.

        ``include_inside`` adds the items of every place below it; ``limit``
        and ``offset`` slice the answer in the database.
        """
        from app.services.storage._queries import list_items_in_location_async

        items = await list_items_in_location_async(
            db,
            organization_id,
            storage_id,
            include_inside=include_inside,
            limit=limit,
            offset=offset,
        )
        return [ItemDTO.model_validate(i) for i in items]

    async def count_items_in_location_async(
        self, db: AsyncSession, organization_id: UUID, storage_id: UUID
    ) -> int:
        """Count non-deleted items in *storage_id*."""
        from app.services.storage._queries import count_items_in_location_async

        return await count_items_in_location_async(db, organization_id, storage_id)

    async def count_items_in_subtree_async(
        self, db: AsyncSession, organization_id: UUID, storage_id: UUID
    ) -> int:
        """Count non-deleted items in *storage_id* and all its descendants."""
        from app.services.storage._queries import count_items_in_subtree_async

        return await count_items_in_subtree_async(db, organization_id, storage_id)

    async def descendant_ids_async(
        self, db: AsyncSession, organization_id: UUID, storage_id: UUID
    ) -> list[UUID]:
        """All storage ids below *storage_id* (excludes the node itself).

        A location named on a document is often a zone rather than a shelf, so
        anything scoped to "this location" has to decide whether the shelves
        under it count. Callers that want the subtree prepend the node.
        """
        from app.services.storage._queries import descendant_ids_async

        return await descendant_ids_async(db, organization_id, storage_id)

    async def list_holding_stock_with_ancestors_async(
        self, db: AsyncSession, organization_id: UUID, *, usage: str = 'internal'
    ) -> list[StorageDTO]:
        """The locations of *usage* holding a live record, with the chains above them.

        Ordered by name. Work that speaks of every location holding stock
        (a count task per shelf) uses this instead of listing the
        organization's locations: the empty ones are not read, and each holder
        arrives with the ancestors its path is made of.
        """
        from app.services.storage._queries import (
            list_holding_stock_with_ancestors_async as _list,
        )

        rows = await _list(db, organization_id, usage=usage)
        return [StorageDTO.model_validate(s) for s in rows]

    async def list_by_ids_async(
        self, db: AsyncSession, organization_id: UUID, storage_ids: Iterable[UUID]
    ) -> list[StorageDTO]:
        """The named locations that exist and are not archived, ordered by name."""
        from app.services.storage._queries import list_storages_by_ids_async

        rows = await list_storages_by_ids_async(db, organization_id, storage_ids)
        return [StorageDTO.model_validate(s) for s in rows]

    async def subtree_and_ancestors_async(
        self, db: AsyncSession, organization_id: UUID, storage_id: UUID
    ) -> tuple[list[StorageDTO], list[StorageDTO]]:
        """``(subtree, ancestors)`` of a location, without reading the rest of the tree.

        The subtree starts with the location itself; the ancestors run nearest
        first. A missing or archived location answers ``([], [])``. Work that
        concerns one location and what hangs from it (a lock, a snapshot, a
        count) uses this instead of listing the organization's locations.
        """
        from app.services.storage._queries import subtree_and_ancestors_async

        subtree, ancestors = await subtree_and_ancestors_async(
            db, organization_id, storage_id
        )
        return (
            [StorageDTO.model_validate(s) for s in subtree],
            [StorageDTO.model_validate(s) for s in ancestors],
        )

    async def count_expiring_soon_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_id: UUID,
        *,
        days: int = 7,
    ) -> int:
        """Count non-deleted items in *storage_id* expiring within *days*.

        ``expiry_date`` is the only indexed date column on Item that passes
        the 3-vertical test; vertical-specific dates live in
        ``Item.meta_data`` and need a different query path (the
        fake ``field_name`` genericity is gone).
        """
        from app.services.storage._queries import count_expiring_soon_async

        return await count_expiring_soon_async(
            db, organization_id, storage_id, days=days
        )
