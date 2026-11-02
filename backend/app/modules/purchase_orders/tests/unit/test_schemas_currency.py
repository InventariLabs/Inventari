from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.purchase_orders.schemas import (
    PartnerPricelistCreate,
    PurchaseOrderCreate,
)


@pytest.mark.unit
class TestCurrencyValidation:
    """The currency field used to accept any three letters."""

    def test_pricelist_rejects_non_iso_code(self) -> None:
        with pytest.raises(ValidationError):
            PartnerPricelistCreate(
                partner_id=uuid4(),
                product_template_id=uuid4(),
                unit_price=Decimal('10.00'),
                valid_from=date(2026, 8, 1),
                currency='DOL',
            )

    def test_pricelist_normalises_lowercase_iso_code(self) -> None:
        model = PartnerPricelistCreate(
            partner_id=uuid4(),
            product_template_id=uuid4(),
            unit_price=Decimal('10.00'),
            valid_from=date(2026, 8, 1),
            currency='eur',
        )
        assert model.currency == 'EUR'

    def test_purchase_order_rejects_non_iso_code(self) -> None:
        with pytest.raises(ValidationError):
            PurchaseOrderCreate(
                lines=[{'name': 'Widget', 'quantity_ordered': Decimal('1')}],
                currency='ABC',
            )

    def test_purchase_order_accepts_iso_code(self) -> None:
        model = PurchaseOrderCreate(
            lines=[{'name': 'Widget', 'quantity_ordered': Decimal('1')}],
            currency='USD',
        )
        assert model.currency == 'USD'
