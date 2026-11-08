"""``CoreAdminAPI`` — public Core API namespace for superadmin analytics read-models.

These are global-scope (non-tenant) aggregates used by the cloud/SaaS admin
dashboard. They live behind ``core_api.admin`` so an extracted cloud module
can consume them without importing ``app.models.*``, which the module import
lint keeps out.

All methods are READ-ONLY (no flush, no commit). Callers own the transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.contracts import (
    AdminOrgMetricsDTO,
    GlobalAdminStatsDTO,
    UserContextDTO,
)
from app.core.public_api._access import reads
from app.i18n.service import get_current_lang, get_error_message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _require_superuser(user: UserContextDTO) -> None:
    """Gate: raise PermissionError if the caller is not a superuser.

    Community modules must not access cross-tenant admin data without
    elevated privileges. Zero in-repo CoreAPI consumers — the admin
    router uses admin_service directly — so the gate is safe to enforce.
    """
    if not user.is_superuser:
        raise PermissionError(
            get_error_message('superuser_required', get_current_lang())
        )


class CoreAdminAPI:
    """Public Core API namespace for superadmin analytics.

    All methods require a ``user: UserContextDTO`` with ``is_superuser=True``
    (cross-tenant surface isolation).
    """

    @reads
    async def list_org_metrics_async(
        self, db: AsyncSession, *, user: UserContextDTO
    ) -> list[AdminOrgMetricsDTO]:
        """List all organizations with SaaS metrics (members/items/storage/value/activity)."""
        _require_superuser(user)
        from app.services.admin_metrics_service import list_org_metrics_async

        return await list_org_metrics_async(db)

    @reads
    async def get_global_stats_async(
        self, db: AsyncSession, *, user: UserContextDTO
    ) -> GlobalAdminStatsDTO:
        """Global system stats: totals, DAU/WAU, LLM cost, scans."""
        _require_superuser(user)
        from app.services.admin_metrics_service import get_global_admin_stats_async

        return await get_global_admin_stats_async(db)
