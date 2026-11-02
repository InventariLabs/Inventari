"""Supplier-price port for indicative costs; accounting still uses layers.

The owning feature registers the provider at import, like the period guard.
Without it the Core estimate has only cost layers to ask. Providers return
rates per stock unit in the requesting organization's currency.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class UnitCostEstimate:
    """An indicative stock-unit cost, its currency and its provenance."""

    unit_cost: Decimal | None = None
    currency: str | None = None
    source: Literal['layers', 'supplier', 'unknown'] = 'unknown'


SupplierPriceProvider = Callable[
    [AsyncSession, UUID, list[UUID], str | None], Awaitable[dict[UUID, Decimal]]
]
_supplier_provider: SupplierPriceProvider | None = None


def register_supplier_price_provider(provider: SupplierPriceProvider) -> None:
    """Register the feature-owned, organization-scoped batch price reader."""
    global _supplier_provider
    _supplier_provider = provider


async def supplier_rates_async(
    db: AsyncSession, organization_id: UUID, ids: list[UUID], currency: str | None
) -> dict[UUID, Decimal]:
    """Read supplier rates, or no rates when the installation has no provider."""
    if _supplier_provider is None or not ids:
        return {}
    return await _supplier_provider(db, organization_id, ids, currency)
