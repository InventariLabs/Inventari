"""Every stats row that names a category also hands over its code.

The screen names a seeded category in the reader's language through its
code; the name on the record is the seed's English fallback. A row that
carries the name alone forces the screen to print that English — "Deli" on
the rotation card, a tab away from "Cold cuts" everywhere else. The field
for the code once existed on these responses and was never filled, so the
screen's translation call was dead while every gate stayed green; these
tests are the line that broke.

Two categories share the name "Deli" here on purpose: one seeded (code
``deli``), one somebody typed. Grouped by name they collapse into a single
row that cannot say which code it has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records


@dataclass
class _Seeded:
    seeded: Category
    typed: Category


@pytest.fixture
def two_delis(
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> _Seeded:
    """A seeded and a hand-named "Deli", with stock, purchases and waste."""
    org_id = test_user.organization_id
    seeded = Category(name='Deli', code='deli', organization_id=org_id)
    typed = Category(name='Deli', organization_id=org_id)
    # Low stock: two on the shelf, five wanted.
    template = ProductTemplate(
        name='Salami', organization_id=org_id, min_quantity=Decimal('5')
    )
    db_session.add_all([seeded, typed, template])
    db_session.flush()

    today = date.today()

    def item(name: str, category: Category, days_ago: int) -> Item:
        return Item(
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            category_id=category.id,
            template_id=template.id if name == 'Salami' else None,
            name=name,
            quantity=2,
            purchase_price=Decimal('10.00'),
            added_date=today - timedelta(days=days_ago),
        )

    # Dead stock, a slow mover, and a second purchase of the same product.
    dead = item('Salami', seeded, 100)
    slow = item('Salami', seeded, 40)
    homemade = item('Home ham', typed, 40)
    db_session.add_all([dead, slow, homemade])
    anchor_pending_records(db_session)
    db_session.flush()

    # A disposal, both halves the report reads: the history row and the
    # outgoing layer that prices it.
    db_session.add(
        ItemHistory(
            organization_id=dead.organization_id,
            item_id=dead.id,
            action='DISPOSED',
            changes={'qty': 1.0, 'old': 2.0, 'reason': 'EXPIRED'},
        )
    )
    db_session.add(
        StockValuationLayer(
            organization_id=org_id,
            product_template_id=template.id,
            item_id=dead.id,
            quantity=Decimal('1'),
            remaining_qty=Decimal('0'),
            unit_cost=Decimal('10.00'),
            total_value=Decimal('10.00'),
            direction='OUT',
            reason='DISPOSED',
        )
    )
    db_session.commit()
    return _Seeded(seeded=seeded, typed=typed)


def _get(client: TestClient, headers: dict[str, str], path: str) -> Any:
    response = client.get(f'/api/v1/stats/{path}', headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.usefixtures('two_delis')
class TestCategoryRowsCarryTheirCode:
    def test_rotation_by_category_keeps_the_two_delis_apart(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        rows = _get(client, auth_headers, 'rotation-analysis')['rotation_by_category']
        delis = sorted(
            (r['category_code'] or '', r['item_count'])
            for r in rows
            if r['category_name'] == 'Deli'
        )
        assert delis == [('', 1), ('deli', 2)]

    def test_rotation_item_rows_name_the_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        data = _get(client, auth_headers, 'rotation-analysis')
        dead = [r for r in data['dead_stock'] if r['name'] == 'Salami']
        slow = [r for r in data['slow_movers'] if r['name'] == 'Salami']
        assert [r['category_code'] for r in dead] == ['deli']
        assert [r['category_code'] for r in slow] == ['deli']

    def test_cost_analysis_rows_name_the_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        data = _get(client, auth_headers, 'cost-analysis')
        by_code = {
            r['category_code']: r
            for r in data['top_expensive_categories']
            if r['category_name'] == 'Deli'
        }
        assert set(by_code) == {'deli', None}
        # The waste lands on the seeded category, not on its namesake.
        assert by_code['deli']['total_wasted'] == pytest.approx(10.0)
        assert by_code[None]['total_wasted'] == 0.0

        opportunity = next(
            o for o in data['savings_opportunities'] if o['product_name'] == 'Salami'
        )
        assert opportunity['category_code'] == 'deli'

    def test_expense_forecast_drivers_name_the_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        drivers = _get(client, auth_headers, 'expense-forecast')['top_cost_drivers']
        assert sorted(
            d['category_code'] or '' for d in drivers if d['category_name'] == 'Deli'
        ) == ['', 'deli']

    def test_purchase_patterns_name_the_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        products = _get(client, auth_headers, 'purchase-patterns')[
            'top_recurring_products'
        ]
        salami = next(p for p in products if p['name'] == 'Salami')
        assert salami['category_code'] == 'deli'

    def test_consumption_rows_name_the_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        wasted = _get(client, auth_headers, 'consumption')['most_wasted']
        assert [w['category_code'] for w in wasted if w['name'] == 'Salami'] == ['deli']
