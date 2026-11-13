from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import OrganizationDTO, UserContextDTO
from app.core.exceptions import ContractViolationError, ServiceRejectionError
from app.core.public_api._access import reads, writes
from app.services._org_reads import DEFERRED_DTO_COLUMNS
from app.services.crypto_service import decrypt_settings

if TYPE_CHECKING:
    from app.models.organization import Organization


class CoreOrganizationsAPI:
    """Public Core API for module-safe organization access."""

    # Columns on Organization that are marked ``deferred`` so
    # legacy installations without the migration do not crash. Single-row
    # paths refresh them before constructing the DTO; list paths eager-load
    # them via ``undefer`` in ``app.services._org_reads``. The list lives
    # with the DTO whose from_attributes read demands it (contracts),
    # so the Public API never imports the model.
    @property
    def deferred_dto_columns(self) -> tuple[str, ...]:
        return DEFERRED_DTO_COLUMNS

    async def _refresh_deferred_async(
        self, db: AsyncSession, org: Organization
    ) -> None:
        await db.refresh(org, list(self.deferred_dto_columns))

    @reads
    async def today_async(self, db: AsyncSession, organization_id: UUID) -> date:
        """What day it is where this organization is.

        For comparisons against date columns, and for anything that decides
        whether an operation may happen at all — a period guard reading the
        server's day told a warehouse in Auckland the month had closed at
        11am on the last day it was still open there.
        """
        from app.services.analytics._common import org_today_async

        return await org_today_async(db, organization_id)

    @reads
    async def timezone_async(self, db: AsyncSession, organization_id: UUID) -> tzinfo:
        """The organization's own clock.

        For pinning a wall-clock deadline to the end of its own day where
        the organization lives, rather than where the server does. An
        unusable stored zone falls back to UTC.
        """
        from app.services.analytics._common import org_timezone_async

        return await org_timezone_async(db, organization_id)

    @reads
    async def window_start_async(
        self, db: AsyncSession, organization_id: UUID, days: int
    ) -> datetime:
        """The instant *days* local days ago began, as a point in time.

        A bare date compared against a timestamp column is read as midnight
        UTC, so a window measured that way starts at a moment with nothing to
        do with the organization's morning.
        """
        from app.services.analytics._common import org_window_start_async

        return await org_window_start_async(db, organization_id, days)

    @reads
    async def get_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> OrganizationDTO | None:
        from app.services._org_reads import (
            get_by_id_async,
        )

        org = await get_by_id_async(db, organization_id)
        if org is None:
            return None
        await self._refresh_deferred_async(db, org)
        return OrganizationDTO.model_validate(org)

    @reads
    async def get_settings_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> dict[str, Any] | None:
        from app.services._org_reads import (
            get_by_id_async,
        )

        organization = await get_by_id_async(db, organization_id)
        if organization is None:
            return None
        return decrypt_settings(organization.settings or {})

    @reads
    async def get_name_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> str | None:
        """Async: return the organization name, or ``None`` if not found."""
        from app.services._org_reads import (
            get_by_id_async,
        )

        organization = await get_by_id_async(db, organization_id)
        return organization.name if organization else None

    @reads
    async def is_module_enabled_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module_name: str,
    ) -> bool:
        from app.services._org_reads import (
            is_module_enabled_async,
        )

        return await is_module_enabled_async(db, organization_id, module_name)

    @writes
    async def update_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        **fields: Any,
    ) -> OrganizationDTO | None:
        """Update organization fields."""
        from app.services._org_reads import (
            get_by_id_async,
        )

        org = await get_by_id_async(db, organization_id)
        if org is None:
            return None

        allowed = {
            'allowed_modules',
            'short_id',
            'settings',
            'name',
            'currency',
            'tax_id',
            'country',
            'address',
            'logo_url',
        }
        for field, value in fields.items():
            if field in allowed and hasattr(org, field):
                setattr(org, field, value)

        await db.flush()
        await db.refresh(org)
        await self._refresh_deferred_async(db, org)
        return OrganizationDTO.model_validate(org)

    @reads
    async def list_missing_short_id_async(
        self, db: AsyncSession
    ) -> list[OrganizationDTO]:
        """List organizations without a short_id (startup repair)."""
        from app.services._org_reads import (
            list_missing_short_id,
        )

        orgs = await list_missing_short_id(db)
        return [OrganizationDTO.model_validate(o) for o in orgs]

    @reads
    async def list_all_async(self, db: AsyncSession) -> list[OrganizationDTO]:
        """Async: list all organizations (superadmin only)."""
        from app.services._org_reads import (
            list_all_async,
        )

        orgs = await list_all_async(db)
        return [OrganizationDTO.model_validate(o) for o in orgs]

    @writes
    async def apply_onboarding_profile_async(
        self,
        db: AsyncSession,
        organization: OrganizationDTO,
        profile_id: str,
        user: UserContextDTO | None = None,
        currency: str | None = None,
        modules: list[str] | None = None,
        timezone: str | None = None,
        organization_name: str | None = None,
        country: str | None = None,
        use_country_preset: bool = False,
    ) -> OrganizationDTO:
        """Apply a product profile to *organization* (idempotent onboarding).

        Delegates to the async ``apply_onboarding_profile_async`` service.
        """
        from app.services._org_reads import (
            get_by_id_async,
        )
        from app.services.onboarding_service import apply_onboarding_profile_async

        org_model = await get_by_id_async(db, organization.id)
        if org_model is None:
            raise ServiceRejectionError('organization_not_found')
        await apply_onboarding_profile_async(
            db,
            org_model,
            profile_id,
            user=user,
            currency=currency,
            modules=modules,
            timezone=timezone,
            organization_name=organization_name,
            country=country,
            use_country_preset=use_country_preset,
        )

        result = await self.get_async(db, organization.id)
        if result is None:
            raise ContractViolationError(
                f'Organization {organization.id} disappeared after onboarding'
            )
        return result

    @writes
    async def toggle_module_async(
        self,
        db: AsyncSession,
        organization: OrganizationDTO,
        module_name: str,
        enabled: bool,
        user: UserContextDTO,
    ) -> list[str]:
        """Toggle a module on/off for *organization*. Returns the new enabled list."""
        from app.services._org_reads import (
            get_by_id_async,
        )
        from app.services.module_service import ModuleService

        org_model = await get_by_id_async(db, organization.id)
        if org_model is None:
            raise ServiceRejectionError('organization_not_found')

        return await ModuleService.toggle_module(
            db, org_model, module_name, enabled, user
        )
