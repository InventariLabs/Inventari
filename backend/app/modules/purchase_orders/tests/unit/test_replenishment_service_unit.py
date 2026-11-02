"""Tests for the replenishment service."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.purchase_orders.replenishment_service import (
    get_replenishment_alerts,
)


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_reserve_shelves() -> Any:
    """These tests pin the alert arithmetic; the reserve search adds none.

    The service reads the location tree, the batches and the transfers
    already on their way so an alert can carry its proposal. Here there is no
    tree, no batch and nothing in flight: every quantity stands on the rule's
    own shelf, which is where the reserve proposal has nothing to offer
    anyway.
    """
    with (
        patch(
            'app.core.public_api.core_api.locations.list_async',
            AsyncMock(return_value=[]),
        ),
        patch(
            'app.core.public_api.core_api.stock.list_lots_async',
            AsyncMock(return_value=[]),
        ),
        patch(
            'app.modules.purchase_orders.replenishment_service._in_flight_inbound_async',
            AsyncMock(return_value={}),
        ),
    ):
        yield


def _make_rule(
    *,
    product_template_id: UUID | None = None,
    storage_location_id: UUID | None = None,
    min_quantity: Decimal = Decimal('10'),
    max_quantity: Decimal = Decimal('20'),
    safety_stock: Decimal = Decimal('2'),
    product_template: Any | None = None,
    preferred_partner_id: UUID | None = None,
    preferred_partner: Any | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_template_id=product_template_id or uuid4(),
        storage_location_id=storage_location_id or uuid4(),
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        safety_stock=safety_stock,
        preferred_partner_id=preferred_partner_id,
        preferred_partner=preferred_partner,
        product_template=(
            product_template
            if product_template is not None
            else SimpleNamespace(name='Test Product', sku='SKU-TEST')
        ),
    )


def _make_quant(
    *,
    quantity: Decimal = Decimal('10'),
    reserved_quantity: Decimal = Decimal('0'),
    storage_location_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        quantity=quantity,
        reserved_quantity=reserved_quantity,
        location_id=storage_location_id,
    )


class _FakeDB:
    """Bare-bones db stub that returns the configured quants."""

    def __init__(self, quants_by_template: dict[UUID, list[Any]]) -> None:
        self._by_template: dict[UUID, list[Any]] = quants_by_template

    async def _list_quants(
        self,
        db: Any,
        org_id: UUID,
        product_template_id: UUID | None = None,
        **_: Any,
    ) -> list[Any]:
        if product_template_id is None:
            return []
        return self._by_template.get(product_template_id, [])


@pytest.mark.unit
class TestGetReplenishmentAlertsPerLocation:
    """Unit tests with patched list_for_org_async + list_quants_async."""

    def test_no_alerts_when_no_rules(self) -> None:
        with patch(
            'app.modules.purchase_orders.replenishment_service.list_for_org_async',
            AsyncMock(return_value=[]),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))
        assert alerts == []

    def test_no_alert_when_stock_sufficient(self) -> None:
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl, storage_location_id=loc, min_quantity=Decimal('5')
        )
        quant = _make_quant(
            quantity=Decimal('10'),
            reserved_quantity=Decimal('0'),
            storage_location_id=loc,
        )
        fake = _FakeDB({tpl: [quant]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))
        assert alerts == []

    def test_alert_when_stock_below_minimum(self) -> None:
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl,
            storage_location_id=loc,
            min_quantity=Decimal('10'),
            max_quantity=Decimal('25'),
            safety_stock=Decimal('3'),
        )
        quant = _make_quant(
            quantity=Decimal('5'),
            reserved_quantity=Decimal('0'),
            storage_location_id=loc,
        )
        fake = _FakeDB({tpl: [quant]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        a = alerts[0]
        assert a.product_template_id == tpl
        assert a.location_id == loc
        assert a.product_name == 'Test Product'
        assert a.sku == 'SKU-TEST'
        assert a.available_quantity == 5.0
        assert a.min_quantity == 10.0
        assert a.shortage == 5.0
        assert a.suggested_reorder_quantity == 20.0

    def test_alert_when_stock_below_safety_even_above_minimum(self) -> None:
        # The rule promises stock never falls below the safety stock, and
        # the form says so in every language; a quantity sitting between
        # the minimum and the safety used to sit there unalerted (the
        # promise broken exactly when the safety stands above the
        # minimum).
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl,
            storage_location_id=loc,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('25'),
            safety_stock=Decimal('8'),
        )
        quant = _make_quant(quantity=Decimal('6'), storage_location_id=loc)
        fake = _FakeDB({tpl: [quant]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        a = alerts[0]
        assert a.available_quantity == 6.0
        assert a.shortage == 2.0
        assert a.suggested_reorder_quantity == 19.0

    def test_the_suggestion_never_leaves_stock_below_safety(self) -> None:
        # A max below the safety cannot be the top-up target: the order
        # the alert suggests has to clear the safety first.
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl,
            storage_location_id=loc,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('7'),
            safety_stock=Decimal('8'),
        )
        quant = _make_quant(quantity=Decimal('5'), storage_location_id=loc)
        fake = _FakeDB({tpl: [quant]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        assert alerts[0].shortage == 3.0
        assert alerts[0].suggested_reorder_quantity == 3.0

    def test_stock_at_other_location_does_not_count(self) -> None:
        loc_a = uuid4()
        loc_b = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl,
            storage_location_id=loc_b,
            min_quantity=Decimal('5'),
        )
        quant_in_a = _make_quant(
            quantity=Decimal('20'),
            reserved_quantity=Decimal('0'),
            storage_location_id=loc_a,
        )
        fake = _FakeDB({tpl: [quant_in_a]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        assert alerts[0].location_id == loc_b
        assert alerts[0].available_quantity == 0.0

    def test_accounts_for_reserved_quantity(self) -> None:
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl, storage_location_id=loc, min_quantity=Decimal('10')
        )
        quant = _make_quant(
            quantity=Decimal('10'),
            reserved_quantity=Decimal('5'),
            storage_location_id=loc,
        )
        fake = _FakeDB({tpl: [quant]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert alerts[0].available_quantity == 5.0
        assert alerts[0].shortage == 5.0

    def test_no_quants_means_zero_available(self) -> None:
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl, storage_location_id=loc, min_quantity=Decimal('5')
        )
        fake = _FakeDB({})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        assert alerts[0].available_quantity == 0.0

    def test_multiple_rules_one_alert_per_low_rule(self) -> None:
        loc_a = uuid4()
        loc_b = uuid4()
        tpl_a = uuid4()
        tpl_b = uuid4()
        rule_a = _make_rule(
            product_template_id=tpl_a,
            storage_location_id=loc_a,
            min_quantity=Decimal('5'),
        )
        rule_b = _make_rule(
            product_template_id=tpl_b,
            storage_location_id=loc_b,
            min_quantity=Decimal('10'),
        )
        quant_a = _make_quant(quantity=Decimal('20'), storage_location_id=loc_a)
        quant_b = _make_quant(quantity=Decimal('3'), storage_location_id=loc_b)
        fake = _FakeDB({tpl_a: [quant_a], tpl_b: [quant_b]})
        with (
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule_a, rule_b]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert len(alerts) == 1
        assert alerts[0].product_template_id == tpl_b


class TestARuleWithNoThresholdIsNotSilentlySkipped:
    """A rule at 0 cannot fire, and the engine used to drop it without a word.

    The API refuses to write one now, so this is a row from before that: it
    sits on the list looking like every other rule and produces nothing. It
    stays skipped — an alert with a threshold of zero is not an alert — but it
    says so where the operator of an installation can find out, which is the
    only channel a row already in the database has.
    """

    def test_the_skip_is_logged_with_the_rule_it_concerns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        loc = uuid4()
        tpl = uuid4()
        rule = _make_rule(
            product_template_id=tpl,
            storage_location_id=loc,
            min_quantity=Decimal('0'),
        )
        quant = _make_quant(
            quantity=Decimal('0'),
            reserved_quantity=Decimal('0'),
            storage_location_id=loc,
        )
        fake = _FakeDB({tpl: [quant]})
        with (
            caplog.at_level('WARNING'),
            patch(
                'app.modules.purchase_orders.replenishment_service.list_for_org_async',
                AsyncMock(return_value=[rule]),
            ),
            patch(
                'app.core.public_api.core_api.stock.list_quants_async',
                fake._list_quants,
            ),
        ):
            alerts = _run(get_replenishment_alerts(MagicMock(), uuid4()))

        assert alerts == []
        assert str(rule.id) in caplog.text
        assert 'minimum' in caplog.text.lower()
