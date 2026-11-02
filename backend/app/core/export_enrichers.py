"""Export-enricher registry — inversion of Core → feature-module dependencies.

Feature modules own vertical columns (e.g. equipment's "Assigned To" from
the checkout table). Core's XLSX export must not import a feature module;
instead modules *register* enrichment callables here at import time and the
Core export endpoint calls them through this registry.

Graceful degradation: when no enricher is registered for an enabled module
(or the enricher itself fails), enrichment is simply skipped — a module can
never break the export.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

#: Enriches export rows for one organization: returns
#: ``{item_id: {column_name: value}}`` for the columns the module owns.
ExportEnricherFn = Callable[
    ['AsyncSession', 'UUID'], Awaitable[dict['UUID', dict[str, object]]]
]

_enrichers: dict[str, ExportEnricherFn] = {}


def register_export_enricher(module_name: str, fn: ExportEnricherFn) -> None:
    """Register an enricher (called by the owning module at import time)."""
    _enrichers[module_name] = fn


async def enrich_export_rows(
    db: AsyncSession, organization_id: UUID, enabled_modules: list[str]
) -> dict[UUID, dict[str, object]]:
    """Run every registered enricher whose module is enabled for the org.

    Returns the merged ``{item_id: {column_name: value}}`` map; later
    enrichers win on key collision. Never raises — a failing enricher is
    logged and skipped so the export always completes.
    """
    merged: dict[UUID, dict[str, object]] = {}
    for module_name, fn in _enrichers.items():
        if module_name not in enabled_modules:
            continue
        try:
            result = await fn(db, organization_id)
        except Exception:  # a module enricher must not break the export
            logger.exception(
                'Export enricher %s failed for org %s', module_name, organization_id
            )
            continue
        if not result:
            continue
        for item_id, columns in result.items():
            merged.setdefault(item_id, {}).update(columns)
    return merged
