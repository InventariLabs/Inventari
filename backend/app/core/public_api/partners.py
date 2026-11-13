from __future__ import annotations

import builtins
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    PartnerCreateDTO,
    PartnerDTO,
    PartnerUpdateDTO,
    UserContextDTO,
)
from app.core.public_api._access import reads, writes
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services import partner_service


class CorePartnersAPI:
    """Public Core API for modules needing read/write access to Partners."""

    @reads
    async def get_async(
        self, db: AsyncSession, org_id: uuid.UUID, partner_id: uuid.UUID
    ) -> PartnerDTO | None:
        partner = await partner_service.get_async(db, org_id, partner_id)
        if partner is None:
            return None
        return PartnerDTO.model_validate(partner)

    @reads
    async def list_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        partner_type: str | None = None,
        is_active: bool = True,
        limit: int = 1000,
    ) -> builtins.list[PartnerDTO]:
        """Async: list partners for *org_id* with optional filters."""
        partners, _ = await partner_service.list_partners_async(
            db, org_id, partner_type=partner_type, is_active=is_active, limit=limit
        )
        return [PartnerDTO.model_validate(p) for p in partners]

    @reads
    async def ids_named_like_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        term: str,
    ) -> builtins.list[uuid.UUID]:
        """Ids of the partners whose name contains *term*, for one query.

        The read a module asks to match its own rows by the partner they
        name: the ids are the whole answer, so a caller's query can filter
        on them in the database instead of materializing a partner list the
        public list read would truncate at its limit. Case-insensitive on
        the name; deactivated partners answer too.
        """
        return await partner_service.ids_named_like_async(db, org_id, term)

    @reads
    async def list_by_email_async(
        self, db: AsyncSession, org_id: uuid.UUID, email: str
    ) -> builtins.list[PartnerDTO]:
        partners, _ = await partner_service.list_partners_async(
            db, org_id, search=email, is_active=True, limit=100
        )
        exact = [p for p in partners if p.email == email]
        return [PartnerDTO.model_validate(p) for p in exact]

    @writes
    async def create_async(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        data: PartnerCreateDTO,
        user: UserContextDTO,
    ) -> PartnerDTO:
        """Create a partner through the standard service pipeline.

        Raises ValueError on unique constraint violation (name+type or code).
        Flushes; caller commits.
        """
        partner_create = PartnerCreate(**data.model_dump())
        partner = await partner_service.create_async(
            db, organization_id, partner_create, user.id
        )
        return PartnerDTO.model_validate(partner)

    @writes
    async def update_async(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        partner_id: uuid.UUID,
        data: PartnerUpdateDTO,
        *,
        user_id: uuid.UUID | None = None,
    ) -> PartnerDTO | None:
        """Partial update (PATCH-style). Returns None if partner not found.

        Raises ValueError on unique constraint violation. Journals the fields
        that changed, under *user_id* when the act has a person behind it.
        Flushes; caller commits.
        """
        partner_update = PartnerUpdate(**data.model_dump(exclude_unset=True))
        partner = await partner_service.update_async(
            db, organization_id, partner_id, partner_update, user_id=user_id
        )
        if partner is None:
            return None
        return PartnerDTO.model_validate(partner)

    @writes
    async def deactivate_async(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        partner_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> PartnerDTO | None:
        """Soft-deactivate a partner (sets is_active=False). Returns None if not found.

        Flushes; caller commits. Emits PARTNER_DEACTIVATED event via service
        and journals the change under *user_id*.
        """
        partner = await partner_service.deactivate_async(
            db, organization_id, partner_id, user_id=user_id
        )
        if partner is None:
            return None
        return PartnerDTO.model_validate(partner)

    @writes
    async def activate_async(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        partner_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> PartnerDTO | None:
        """Reactivate a previously deactivated partner. Returns None if not found.

        Flushes; caller commits. Emits PARTNER_ACTIVATED event via service
        and journals the change under *user_id*.
        """
        partner = await partner_service.activate_async(
            db, organization_id, partner_id, user_id=user_id
        )
        if partner is None:
            return None
        return PartnerDTO.model_validate(partner)
