"""Seed a purchase the way the cost ledger sees it.

The spending reports read the receipt layers — what arrived, at what it
cost, on its business date — not the prices typed on the records. A test
that wants "a purchase of 100 three weeks ago" therefore posts a layer,
dated then, worth that.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer


def purchase_template(org_id: UUID, name: str = 'Purchase') -> ProductTemplate:
    """A product to hang receipt layers on; the ledger knows nothing else."""
    return ProductTemplate(
        organization_id=org_id, name=name, sku=f'PUR-{uuid.uuid4().hex[:8]}'
    )


def receipt_layer(
    org_id: UUID,
    template_id: UUID,
    *,
    value: str | Decimal,
    on: date,
    quantity: str | Decimal = '1',
    currency: str | None = None,
) -> StockValuationLayer:
    """One receipt worth ``value`` in total, dated ``on``."""
    qty = Decimal(str(quantity))
    total = Decimal(str(value))
    return StockValuationLayer(
        organization_id=org_id,
        product_template_id=template_id,
        quantity=qty,
        remaining_qty=qty,
        unit_cost=(total / qty).quantize(Decimal('0.0001')),
        total_value=total,
        document_date=on,
        currency=currency,
        direction='IN',
    )
