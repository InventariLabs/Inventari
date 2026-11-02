"""The refusals no request can reach still speak the reader's language.

Five of this task's refusals sit behind a Pydantic threshold the schema
answers first: ``pricelist`` types ``unit_price`` and ``min_quantity`` as
``gt=0`` on both write schemas, ``reorder`` types ``min_quantity`` as
``gt=0`` and ``safety_stock`` as ``ge=0`` on create, and the import router
checks an order's status before it reads the uploaded sheet — so the
service's own half of that check never runs over HTTP.

They are still refusals a reader's screen could show: another door calls
these services directly (the replenishment flow, a future internal caller),
and a guard answered in English is English wherever it is answered. So they
are keyed like the rest, and pinned here at the boundary they are actually
reachable from — the language set the way a request would set it, and the
sentence asserted as text. With the key reverted to its English literal
these assertions fail; the status code would not tell them apart.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ServiceRejectionError
from app.i18n.service import set_current_lang
from app.modules.purchase_orders.po_import_service import import_lines_into_po
from app.modules.purchase_orders.pricelist_service import (
    create_async as create_entry,
)
from app.modules.purchase_orders.pricelist_service import (
    update_async as update_entry,
)
from app.modules.purchase_orders.reorder_service import create_async as create_rule


@pytest.fixture(autouse=True)
def _english_by_default() -> Iterator[None]:
    """A language set here is a contextvar — without the reset it would
    leak into the next test on this worker."""
    set_current_lang('en')
    yield
    set_current_lang('en')


async def _update(**fields: Any) -> object:
    """Patch an entry that already exists — the service refuses before it
    writes, so the session never has to do more than hand the row over."""
    entry = MagicMock()
    entry.id = uuid4()
    entry.partner_id = uuid4()
    entry.product_template_id = uuid4()
    entry.unit_price = Decimal('10')
    entry.currency = 'PLN'
    entry.min_quantity = None
    entry.valid_from = date(2026, 1, 1)
    entry.valid_to = None
    db = MagicMock()
    db.scalar = AsyncMock(return_value=entry)
    return await update_entry(db, organization_id=uuid4(), entry_id=entry.id, **fields)


@pytest.mark.unit
class TestReorderGuardsInReadersLanguage:
    @pytest.mark.asyncio
    async def test_creating_a_rule_below_zero_safety_stock_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await create_rule(
                MagicMock(),
                organization_id=uuid4(),
                product_template_id=uuid4(),
                storage_location_id=uuid4(),
                min_quantity=Decimal('5'),
                max_quantity=Decimal('20'),
                safety_stock=Decimal('-1'),
            )

        assert str(refusal.value) == 'safety_stock musi być >= 0, otrzymano -1'

    @pytest.mark.asyncio
    async def test_creating_a_rule_below_zero_minimum_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await create_rule(
                MagicMock(),
                organization_id=uuid4(),
                product_template_id=uuid4(),
                storage_location_id=uuid4(),
                min_quantity=Decimal('-1'),
                max_quantity=Decimal('20'),
            )

        assert str(refusal.value) == 'min_quantity musi być >= 0, otrzymano -1'


@pytest.mark.unit
class TestPricelistGuardsInReadersLanguage:
    @pytest.mark.asyncio
    async def test_creating_an_entry_with_a_zero_price_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await create_entry(
                MagicMock(),
                organization_id=uuid4(),
                partner_id=uuid4(),
                product_template_id=uuid4(),
                unit_price=Decimal('0'),
                valid_from=date(2026, 1, 1),
            )

        assert str(refusal.value) == 'unit_price musi być > 0, otrzymano 0'

    @pytest.mark.asyncio
    async def test_creating_an_entry_with_a_zero_minimum_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await create_entry(
                MagicMock(),
                organization_id=uuid4(),
                partner_id=uuid4(),
                product_template_id=uuid4(),
                unit_price=Decimal('10'),
                valid_from=date(2026, 1, 1),
                min_quantity=Decimal('0'),
            )

        assert str(refusal.value) == 'min_quantity musi być > 0, otrzymano 0'

    @pytest.mark.asyncio
    async def test_patching_an_entry_to_a_zero_price_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await _update(unit_price=Decimal('0'))

        assert str(refusal.value) == 'unit_price musi być > 0, otrzymano 0'

    @pytest.mark.asyncio
    async def test_patching_an_entry_to_a_zero_minimum_speaks_polish(self) -> None:
        set_current_lang('pl')

        with pytest.raises(ServiceRejectionError) as refusal:
            await _update(min_quantity=Decimal('0'))

        assert str(refusal.value) == 'min_quantity musi być > 0, otrzymano 0'


@pytest.mark.unit
class TestPoImportGuardsInReadersLanguage:
    """Both guards run after the router's own check of the same two facts —
    defense in depth, and a caller inside the module still reads them."""

    @pytest.mark.asyncio
    async def test_importing_into_a_missing_order_speaks_polish(self) -> None:
        set_current_lang('pl')
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ServiceRejectionError) as refusal:
            await import_lines_into_po(
                db, uuid4(), b'name\nWidget\n', 'lines.csv', {}, uuid4()
            )

        assert str(refusal.value) == 'Zamówienie zakupu nie zostało znalezione'

    @pytest.mark.asyncio
    async def test_importing_into_a_confirmed_order_speaks_polish(self) -> None:
        set_current_lang('pl')
        po = MagicMock()
        po.status = 'CONFIRMED'
        po.lines = []
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(ServiceRejectionError) as refusal:
            await import_lines_into_po(
                db, po.id, b'name\nWidget\n', 'lines.csv', {}, uuid4()
            )

        assert str(refusal.value) == (
            'Można importować linie tylko do zamówienia zakupowego w wersji ROBOCZEJ'
        )
