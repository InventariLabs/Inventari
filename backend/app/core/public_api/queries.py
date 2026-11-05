"""Public Core API namespace for analytics read-models.

Wraps :mod:`app.services.analytics` to enforce the CoreAPI contract:
``db.flush()`` only (no commit), DTO returns, organization-scoped reads.

Tier 1 named read-models — domain-neutral aggregates that pass the
3-Vertical Test. Modules build dashboards and reports on top of these
instead of bypassing to ``app.models`` directly. Beside the aggregates
sit the handful of lookup reads a module's screens ask for by id — a
partner's display name, the stock a document holds — which the
entity-per-call namespaces answer only N times over, so a module either
walked them one id at a time or reached past the contract for the join.

Cache strategy: stale-acceptable read-models (overview, rotation,
forecast) are wrapped in :func:`cache_get_or_set` with TTL 300s. The
``reconciliation`` model is intentionally uncached because drift must
be fresh.

Invalidation: every state-changing act funnels through the audit
journal, whose writer calls ``cache_invalidate_org_queries`` — one
``INCR`` on the organization's version key, after which the names
these functions build resolve elsewhere; a bulk item update journals
each row like a single edit and invalidates explicitly on top of it. A
cache entry therefore never survives a write to the records it
aggregates.

Not every journal entry is such a write. The models here are all
defined over stock, catalogue and custody facts, so the journal writer
skips the invalidation for entries about things none of them reads:
who may access the organization (``org_member``, ``role``,
``invitation``, ``api_key``, ``webhook_endpoint``) and somebody's own
working note (``recipe``, ``meal_plan``, ``shopping_list``). Adding a
cached read-model that reads any of those means taking the target back
out of ``_ANALYTICS_NEUTRAL_TARGETS`` in ``app/services/audit_service``
— ``tests/integration/test_stats_cache_invalidation.py`` fails until
somebody says which way it goes.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_or_set, org_query_key
from app.core.contracts import (
    ActivityDTO,
    CategoryStatsDTO,
    ConsumptionStatsDTO,
    CostSummaryDTO,
    DocumentReservationHoldDTO,
    ExpenseForecastDTO,
    ExpiryBucketDTO,
    LowStockProductDTO,
    OverviewDTO,
    PreviousMeasurementDTO,
    ReconciliationDTO,
    RotationAnalysisDTO,
    StorageStatsDTO,
)

_ANALYTICS_CACHE_TTL_SECONDS = 300


class CoreQueriesAPI:
    """Public Core API namespace for analytics read-models."""

    async def get_overview_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> OverviewDTO:
        """High-level inventory health snapshot for an organization.

        Cached for 300 s; dashboards tolerate up to 5 minutes of staleness.
        """
        from app.services.analytics.overview import get_overview_async as _get

        async def _factory() -> OverviewDTO:
            return await _get(db, organization_id)

        return await cache_get_or_set(  # type: ignore[no-any-return]
            await org_query_key(organization_id, 'overview'),
            ttl=_ANALYTICS_CACHE_TTL_SECONDS,
            factory=_factory,
            deserializer=OverviewDTO.model_validate_json,
        )

    async def get_low_stock_products_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        limit: int = 100,
        exclude_module_contexts: bool = False,
        offset: int = 0,
    ) -> list[LowStockProductDTO]:
        """The products the overview's ``low_stock`` number counts, emptiest first.

        Same rule and same query as the number, so the list never holds a
        different set than the figure it explains. Not cached: it is a short
        list a reader opens to act on. ``exclude_module_contexts`` is the item
        list's own filter, the one ``attention-counts`` takes.
        """
        from app.services.items.low_stock import low_stock_products_async

        return await low_stock_products_async(
            db, organization_id, limit, exclude_module_contexts, offset
        )

    async def count_low_stock_products_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        exclude_module_contexts: bool = False,
    ) -> int:
        """How many products :meth:`get_low_stock_products_async` pages through.

        The overview's ``low_stock`` number, from the same count, so a page's
        ``total`` and the figure it explains cannot disagree.
        """
        from app.services.items.low_stock import (
            claimed_tags_for,
            low_stock_count_async,
        )

        return await low_stock_count_async(
            db, organization_id, claimed_tags_for(exclude_module_contexts)
        )

    async def get_stats_by_storage_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[StorageStatsDTO]:
        """Item counts and expiry aggregates per storage location."""
        from app.services.analytics.dashboard import get_stats_by_storage_async as _get

        return await _get(db, organization_id)

    async def get_stats_by_category_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[CategoryStatsDTO]:
        """Item counts and stock value aggregated per category."""
        from app.services.analytics.dashboard import get_stats_by_category_async as _get

        return await _get(db, organization_id)

    async def get_expiry_forecast_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[ExpiryBucketDTO]:
        """Six time-bucketed expiry counts for an organization."""
        from app.services.analytics.dashboard import get_expiry_forecast_async as _get

        return await _get(db, organization_id)

    async def get_recent_activity_async(
        self, db: AsyncSession, organization_id: UUID, *, limit: int = 10
    ) -> list[ActivityDTO]:
        """Recent ItemHistory entries with item and user names."""
        from app.services.analytics.dashboard import get_recent_activity_async as _get

        return await _get(db, organization_id, limit)

    async def get_consumption_stats_async(
        self, db: AsyncSession, organization_id: UUID, *, days: int = 30
    ) -> ConsumptionStatsDTO:
        """Usage and disposal aggregates over a time window."""
        from app.services.analytics.consumption import (
            get_consumption_stats_async as _get,
        )

        return await _get(db, organization_id, days)

    async def get_cost_summary_async(
        self, db: AsyncSession, organization_id: UUID, *, period: str = 'month'
    ) -> CostSummaryDTO:
        """Cost analysis: spent, wasted, trends, savings opportunities."""
        from app.services.analytics.cost import get_cost_summary_async as _get

        return await _get(db, organization_id, period)

    async def get_rotation_analysis_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> RotationAnalysisDTO:
        """Inventory rotation metrics: age, slow movers, dead stock.

        Cached for 300 s; rotation analyses change slowly.
        """
        from app.services.analytics.rotation import (
            get_rotation_analysis_async as _get,
        )

        async def _factory() -> RotationAnalysisDTO:
            return await _get(db, organization_id)

        return await cache_get_or_set(  # type: ignore[no-any-return]
            await org_query_key(organization_id, 'rotation'),
            ttl=_ANALYTICS_CACHE_TTL_SECONDS,
            factory=_factory,
            deserializer=RotationAnalysisDTO.model_validate_json,
        )

    async def get_reconciliation_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> ReconciliationDTO:
        """The shelf against the movement ledger and against the cost layers."""
        from app.services.analytics.reconciliation import (
            get_reconciliation_async as _get,
        )

        return await _get(db, organization_id)

    async def get_reconciliation_previous_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> PreviousMeasurementDTO | None:
        """What the previous scheduled reconciliation pass measured.

        The scheduled job stores each pass under one settings key — the same
        record its drift warning compares against — so the screen's
        "previous" is the measurement that decided the last warning, not a
        second number kept elsewhere. ``None`` before the first pass runs.
        """
        from app.services.reconciliation_job import read_previous_measurement_async

        return await read_previous_measurement_async(db, organization_id)

    async def get_expense_forecast_async(
        self, db: AsyncSession, organization_id: UUID, *, period: str = 'month'
    ) -> ExpenseForecastDTO:
        """Predicted future spending derived from historical purchase trends.

        Cached per (org, period) for 300 s.
        """
        from app.services.analytics.forecast import (
            get_expense_forecast_async as _get,
        )

        async def _factory() -> ExpenseForecastDTO:
            return await _get(db, organization_id, period)

        return await cache_get_or_set(  # type: ignore[no-any-return]
            await org_query_key(organization_id, f'forecast:{period}'),
            ttl=_ANALYTICS_CACHE_TTL_SECONDS,
            factory=_factory,
            deserializer=ExpenseForecastDTO.model_validate_json,
        )

    async def get_partner_display_names_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        partner_ids: Iterable[UUID],
    ) -> dict[UUID, str]:
        """The display name of each partner these ids name, asked in one read.

        A list that prints a name beside a stored partner id used to have
        two bad answers: fetch each partner on its own, an N+1 over the
        page, or take the whole partner list and filter it. This reads
        only the ids the reader shows, deactivated partners included —
        the name a document was filed under still has to print — and an
        id this organization does not own, or that no longer exists, is
        simply absent so the caller falls back to the name it froze with
        the row.
        """
        from app.services.partner_service import (
            display_names_by_ids_async as _display_names,
        )

        return await _display_names(db, organization_id, partner_ids)

    async def get_storage_display_names_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        storage_ids: Iterable[UUID],
    ) -> dict[UUID, str]:
        """The name of each shelf these ids name, asked in one read.

        The shelf half of the partner-name read above, and for the same
        reason: a register grouping documents by the place they moved from
        or to names that place on every group, and archived shelves are
        included — a document filed at a shelf no longer on the lists still
        prints where it went. An id this organization does not own, or one
        that no longer exists, is absent so the caller keeps its fallback.
        """
        from app.services.storage._queries import (
            display_names_by_ids_async as _display_names,
        )

        return await _display_names(db, organization_id, storage_ids)

    async def get_reservations_held_by_documents_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        document_ids: Iterable[UUID],
    ) -> list[DocumentReservationHoldDTO]:
        """Reservations held by each of these documents, per product and shelf.

        One row per document and per group of stock it holds, summed —
        the grain a screen shows a hold at — with the product, its unit
        and the shelf named in the same statement, so a queue of held
        documents resolves its names in one query instead of three per
        row. Only the stock side answers here: the document's own number
        and date stay with the module that owns the document table.
        """
        from app.services._stock_reservation import (
            reservation_holds_by_documents_async as _holds,
        )

        return await _holds(db, organization_id, document_ids)
