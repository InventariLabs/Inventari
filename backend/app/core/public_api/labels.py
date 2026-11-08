"""Module-safe access to LabelPool records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    LabelCodeItemDTO,
    LabelPoolCreateDTO,
    LabelPoolDTO,
    UserContextDTO,
)
from app.core.logging import get_logger
from app.core.public_api._access import reads, writes
from app.services.label_service import LabelService, label_caption

logger = get_logger(__name__)


class CoreLabelsAPI:
    """Public Core API for module-safe LabelPool reads and writes."""

    # ── read ────────────────────────────────────────────────────────

    @reads
    async def get_by_id_async(
        self, db: AsyncSession, label_id: UUID, organization_id: UUID
    ) -> LabelPoolDTO | None:
        """Return a single label by ID scoped to *organization_id*, or ``None``."""
        label = await LabelService.get_by_id_async(db, label_id, organization_id)
        return LabelPoolDTO.model_validate(label) if label else None

    @reads
    async def get_by_short_code_async(
        self, db: AsyncSession, short_code: str, organization_id: UUID
    ) -> LabelPoolDTO | None:
        """Return a single label by short_code scoped to *organization_id*, or ``None``."""
        label = await LabelService.get_by_short_code_async(
            db, short_code, organization_id
        )
        return LabelPoolDTO.model_validate(label) if label else None

    @reads
    async def list_for_org_async(
        self, db: AsyncSession, organization_id: UUID, *, unassigned_only: bool = False
    ) -> list[LabelPoolDTO]:
        """List labels for *organization_id*, optionally filtered to unassigned."""
        labels = await LabelService.list_for_org_async(
            db, organization_id, unassigned_only=unassigned_only
        )
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @reads
    async def list_for_org_with_relations_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        unassigned_only: bool = False,
        label_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[LabelPoolDTO], int]:
        """List labels for *organization_id* with eager-loaded assigned_item.

        The returned DTOs have ``is_item_deleted``, ``assigned_item_name``,
        ``assigned_item_quantity``, ``assigned_item_unit``, and
        ``assigned_item_context_tag`` populated from the relationships.
        Returns ``(dtos, total)`` so callers can build a paginated envelope.
        """
        labels, total = await LabelService.list_for_org_with_relations_async(
            db,
            organization_id,
            unassigned_only=unassigned_only,
            label_type=label_type,
            status=status,
            offset=offset,
            limit=limit,
        )
        return [LabelPoolDTO.model_validate(label) for label in labels], total

    @reads
    async def list_in_ids_async(
        self, db: AsyncSession, label_ids: list[UUID], organization_id: UUID
    ) -> list[LabelPoolDTO]:
        """Return labels whose IDs are in *label_ids* scoped to *organization_id*."""
        labels = await LabelService.list_in_ids_async(db, label_ids, organization_id)
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @reads
    async def list_by_short_codes_async(
        self, db: AsyncSession, short_codes: list[str], organization_id: UUID
    ) -> list[LabelPoolDTO]:
        """Return labels whose short_code is in *short_codes* scoped to *organization_id*."""
        labels = await LabelService.list_by_short_codes_async(
            db, short_codes, organization_id
        )
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @reads
    async def list_unprinted_unassigned_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        limit: int,
        exclude_ids: list[UUID] | None = None,
    ) -> list[LabelPoolDTO]:
        """List unprinted + unassigned labels for *organization_id*."""
        labels = await LabelService.list_unprinted_unassigned_async(
            db, organization_id, limit=limit, exclude_ids=exclude_ids
        )
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @reads
    async def get_pool_stats_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> dict[str, Any]:
        """Return pool stats: total / assigned counts."""
        return await LabelService.get_pool_stats_async(db, organization_id)

    # ── write ───────────────────────────────────────────────────────

    @writes
    async def generate_pool_async(
        self, db: AsyncSession, request: LabelPoolCreateDTO, user: UserContextDTO
    ) -> list[LabelPoolDTO]:
        """Generate a pool of N unique labels."""
        from app.schemas.label_pool import LabelPoolCreate

        internal = LabelPoolCreate(**request.model_dump())
        labels = await LabelService.generate_label_pool_async(db, internal, user)
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @writes
    async def create_from_codes_async(
        self,
        db: AsyncSession,
        codes: list[LabelCodeItemDTO],
        user: UserContextDTO,
        *,
        label_type: str = 'GENERIC',
        context_tag: str | None = None,
    ) -> list[LabelPoolDTO]:
        """Create labels with explicit short_codes (org-scoped)."""
        from app.schemas.label_pool import LabelCodeItem

        internal_codes = [LabelCodeItem(**c.model_dump()) for c in codes]
        labels = await LabelService.create_from_codes_async(
            db,
            internal_codes,
            user,
            label_type=label_type,
            context_tag=context_tag,
        )
        return [LabelPoolDTO.model_validate(label) for label in labels]

    @writes
    async def delete_async(
        self,
        db: AsyncSession,
        label_id: UUID,
        organization_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> bool:
        """Delete a label scoped to *organization_id*. Returns ``False`` when not found.

        Journals the deletion under *user_id*.
        """
        label = await LabelService.get_by_id_async(
            db, label_id, organization_id, for_update=True
        )
        if label is None:
            return False
        await LabelService.delete_label_async(db, label, user_id=user_id)
        return True

    @writes
    async def unassign_async(
        self,
        db: AsyncSession,
        short_code: str,
        organization_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> LabelPoolDTO | None:
        """Unassign a label by short_code (returns refreshed DTO, ``None`` when not found).

        Journals the freed binding under *user_id*.
        """
        label = await LabelService.get_by_short_code_async(
            db, short_code, organization_id, for_update=True
        )
        if label is None:
            return None
        refreshed = await LabelService.unassign_label_async(db, label, user_id=user_id)
        return LabelPoolDTO.model_validate(refreshed)

    @writes
    async def assign_to_existing_item_async(
        self,
        db: AsyncSession,
        short_code: str,
        item_id: UUID,
        organization_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> LabelPoolDTO | None:
        """Assign a label to an existing item (returns refreshed DTO, ``None`` when not found).

        Journals the binding under *user_id*.
        """
        label = await LabelService.get_by_short_code_async(
            db, short_code, organization_id, for_update=True
        )
        if label is None:
            return None
        refreshed = await LabelService.assign_to_existing_item_async(
            db, label, item_id, user_id=user_id
        )
        return LabelPoolDTO.model_validate(refreshed)

    @reads
    def caption(self, label: LabelPoolDTO) -> str | None:
        """The text printed under a label's QR code when nobody typed one.

        The same rule the label export applies: the label's own description,
        else the assigned product's name and expiry month.
        """
        return label_caption(label)

    @writes
    async def mark_as_printed_by_ids_async(
        self, db: AsyncSession, label_ids: list[UUID], organization_id: UUID
    ) -> None:
        """Mark labels as printed by their IDs (scoped to *organization_id*)."""
        await LabelService.mark_as_printed_by_ids_async(db, label_ids, organization_id)
