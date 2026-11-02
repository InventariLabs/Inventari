"""
Module-safe access to location types.

Modules should not query ``StorageType`` directly — they should use this API
to stay within the public contract.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    StorageTypeCreateDTO,
    StorageTypeDTO,
    StorageTypeUpdateDTO,
    UserContextDTO,
)
from app.core.exceptions import ContractViolationError
from app.core.logging import get_logger
from app.i18n._types import SUPPORTED_LANGUAGES, Language
from app.services.storage_type_service import StorageTypeService

logger = get_logger(__name__)


def _validate_lang(lang: str | None) -> Language | None:
    """Validate a language code against the supported set.

    Raises ``ContractViolationError`` for unsupported codes so community modules get a
    clear error instead of silently falling through. Returns the code as
    the internal ``Language`` Literal for the service layer — the
    membership check above guarantees the cast is sound.
    """
    if lang is None:
        return None
    if lang not in SUPPORTED_LANGUAGES:
        raise ContractViolationError(
            f'Unsupported language code: {lang!r}. '
            f'Allowed: {", ".join(sorted(SUPPORTED_LANGUAGES))}'
        )
    return cast(Language, lang)


class CoreStorageTypesAPI:
    """Public Core API for module-safe location type reads and writes."""

    async def list_for_org_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[StorageTypeDTO]:
        """Return the storage types *organization_id* owns, in a stable order.

        Only the organization's own rows come back: every type has an owner
        (seeded by its profile, by a module it enabled, or created by hand).
        It does not include unowned system-wide rows. Sorted by name
        (case-folded), then name, then id.
        """
        types_ = await StorageTypeService.list_for_org_async(db, organization_id)
        return [StorageTypeDTO.model_validate(t) for t in types_]

    async def get_by_id_async(
        self,
        db: AsyncSession,
        storage_type_id: UUID,
        organization_id: UUID,
        *,
        include_global: bool = False,
    ) -> StorageTypeDTO | None:
        """Return a single storage type by ID, or ``None``.

        By default only returns the type if it belongs to *organization_id*
        or is a system type (``organization_id IS NULL``). Pass
        ``include_global=True`` (admin/tooling paths only) to also match
        types owned by other organizations.
        """
        storage_type = await StorageTypeService.get_by_id_async(
            db,
            storage_type_id,
            organization_id=None if include_global else organization_id,
        )
        return StorageTypeDTO.model_validate(storage_type) if storage_type else None

    async def create_async(
        self,
        db: AsyncSession,
        storage_type_in: StorageTypeCreateDTO,
        user: UserContextDTO,
        lang: str | None = None,
    ) -> StorageTypeDTO:
        """Create a new storage type. Returns the StorageTypeDTO."""
        validated_lang = _validate_lang(lang)
        from app.schemas.storage_type import StorageTypeCreate

        internal = StorageTypeCreate(**storage_type_in.model_dump())
        storage_type = await StorageTypeService.create_storage_type_async(
            db, internal, user, validated_lang
        )
        return StorageTypeDTO.model_validate(storage_type)

    async def update_async(
        self,
        db: AsyncSession,
        storage_type_id: UUID,
        storage_type_in: StorageTypeUpdateDTO,
        user: UserContextDTO,
        lang: str | None = None,
    ) -> StorageTypeDTO | None:
        """Update a storage type (handles system forking). Returns updated DTO or None."""
        validated_lang = _validate_lang(lang)
        storage_type = await StorageTypeService.get_by_id_async(
            db, storage_type_id, organization_id=user.organization_id
        )
        if storage_type is None:
            return None
        from app.schemas.storage_type import StorageTypeUpdate

        internal = StorageTypeUpdate(**storage_type_in.model_dump(exclude_unset=True))
        updated = await StorageTypeService.update_storage_type_async(
            db, storage_type, internal, user, validated_lang
        )
        return StorageTypeDTO.model_validate(updated) if updated else None

    async def delete_async(
        self, db: AsyncSession, storage_type_id: UUID, user: UserContextDTO
    ) -> bool:
        """Delete a storage type. Returns ``True`` if deleted, ``False`` if not found."""
        storage_type = await StorageTypeService.get_by_id_async(
            db, storage_type_id, organization_id=user.organization_id
        )
        if storage_type is None:
            return False
        await StorageTypeService.delete_storage_type_async(db, storage_type, user)
        return True
