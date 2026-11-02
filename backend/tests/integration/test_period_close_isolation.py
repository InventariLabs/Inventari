"""
Integration tests: period-close isolation across all stock-mutating paths.

Documents guarded their workflow transitions via inline period checks, but
every other stock-mutating path silently bypassed the inventory lock. Now
every mutation calls ``core_api.periods.check_not_closed_async(db, org_id, date)``
which raises ``PeriodClosedError`` → router maps to ``HTTP 409 PERIOD_CLOSED``.

Tests cover the 5 highest-impact paths:

- consume (item endpoint) — where the bypass was first seen
- move (item endpoint) — storage location transfer
- stock_take finalize — when apply_adjustments writes back deltas
- recipes picking — calls core_api.items.update_quantity_async internally
- create_item (negative test) — must NOT be blocked (it's not a
  stock mutation on existing stock, only a new row)

Period is closed via the existing warehouse module endpoint
(``POST /api/v1/warehouse/periods/{year}/{month}/close``). Closing the
current calendar month therefore blocks ``date.today()`` consumption.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.storage_location import StorageLocation


def _close_current_period(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    """Close the period containing ``date.today()`` (current calendar month)."""
    today = date.today()
    resp = client.post(
        f'/api/v1/warehouse/periods/{today.year}/{today.month}/close',
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _stock_take_id_for_item(db_session: Session, item_id: Any) -> Any | None:
    """Find any open stock_take that contains this item. None if no fixture."""
    try:
        from app.modules.stock_takes.models import StockTakeItem
    except ImportError:
        return None
    return db_session.scalars(
        select(StockTakeItem).where(StockTakeItem.item_id == item_id)
    ).first()


@pytest.mark.integration
class TestPeriodCloseIsolation:
    """Item-side mutations must respect the inventory period lock."""

    def test_consume_after_period_close_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_category: Any,
        test_user: Any,
        db_session: Session,
    ) -> None:
        """Closing the current period blocks real-time consume."""
        from app.models.item import Item as _Item

        item = _Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Period Consume Block',
            quantity=5,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _close_current_period(client, auth_headers)

        resp = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=auth_headers,
            json={'quantity': 1, 'reason': 'test'},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'PERIOD_CLOSED'
        assert 'closed' in detail['message'].lower()

    def test_move_after_period_close_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_storage_type: Any,
        test_category: Any,
        test_user: Any,
        db_session: Session,
    ) -> None:
        """Closing the current period blocks storage moves."""
        from app.models.item import Item as _Item
        from app.models.storage_location import StorageLocation as _Loc

        item = _Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Period Move Block',
            quantity=5,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        target = _Loc(
            organization_id=test_user.organization_id,
            storage_type_id=test_storage_location.storage_type_id,
            created_by=test_user.id,
            name='Period Move Target',
        )
        db_session.add(target)
        db_session.commit()
        db_session.refresh(target)

        _close_current_period(client, auth_headers)

        resp = client.patch(
            f'/api/v1/items/{item.id}/move',
            headers=auth_headers,
            json={'to_location_id': str(target.id)},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == 'PERIOD_CLOSED'

    def test_update_quantity_after_period_close_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_category: Any,
        test_user: Any,
        db_session: Session,
    ) -> None:
        """Closing the current period blocks direct quantity edits."""
        from app.models.item import Item as _Item

        item = _Item(
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name='Period Qty Block',
            quantity=5,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _close_current_period(client, auth_headers)

        resp = client.patch(
            f'/api/v1/items/{item.id}/quantity',
            headers=auth_headers,
            json={'quantity': 3},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == 'PERIOD_CLOSED'

    def test_stock_take_finalize_after_period_close_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        db_session: Session,
    ) -> None:
        """Finalizing a stock_take with apply_adjustments must respect the lock.

        The stock_take fixture already counts all items with their system
        quantities. Finalize with apply_adjustments=True should write
        adjustments back; if the current period is closed, this must 409.
        """
        # Set counted_quantity equal to system_quantity so the finalize
        # would be a no-op-with-write (still triggers update_quantity path).
        from app.modules.stock_takes.models import StockTakeItem

        items = db_session.scalars(
            select(StockTakeItem).where(
                StockTakeItem.stock_take_id == test_stock_take.id
            )
        ).all()
        for sti in items:
            sti.counted_quantity = sti.system_quantity
        db_session.commit()

        _close_current_period(client, auth_headers)

        resp = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/complete',
            headers=auth_headers,
            json={
                'apply_adjustments': True,
                'force_over_cap': True,
                'notes': 'period-close test',
            },
        )
        # Router maps PeriodClosedError → 409 PERIOD_CLOSED.
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'PERIOD_CLOSED'

    def test_create_item_after_period_close_succeeds(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_category: Any,
        test_user: Any,
    ) -> None:
        """Creating a new item is NOT a stock mutation → must NOT 409.

        The period lock guards stock-mutating operations on existing
        inventory. Adding a new item row doesn't touch existing stock;
        it must remain available even when the current period is closed.
        """
        _close_current_period(client, auth_headers)

        resp = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Post-close Create',
                'location_id': str(test_storage_location.id),
                'category_id': str(test_category.id),
                'quantity': 1,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert body['name'] == 'Post-close Create'
        assert Decimal(body['quantity']) == 1

    def test_recipes_picking_after_period_close_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        test_user: Any,
        db_session: Session,
    ) -> None:
        """Scanning an item during recipe picking must respect the period lock.

        Picking calls ``scan_item_in_picking`` which internally calls
        ``core_api.items.update_quantity_async`` — a real-time stock mutation.
        When the current period is closed the scan endpoint must return
        409 PERIOD_CLOSED (not 500, not 400).
        """
        import uuid

        from app.models.product_template import ProductTemplate
        from tests.integration._shelf import post_on_shelf

        # Ingredient template + a record of it on the shelf to pick against.
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Picking Period Ingredient',
        )
        db_session.add(template)
        db_session.commit()
        record = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, 500
        )

        # Recipe referencing the ingredient template.
        recipe_r = client.post(
            '/api/v1/recipes',
            headers=auth_headers,
            json={
                'name': 'Picking Period Recipe',
                'description': 'desc',
                'servings': 2,
                'prep_time_minutes': 10,
                'tags': [],
                'is_favorite': False,
                'ingredients': [
                    {
                        'name': 'Picking Period Ingredient',
                        'template_id': str(template.id),
                        'quantity': '100',
                        # In the unit the stock is kept in, so the scan gets
                        # as far as the period it is about.
                        'uom_id': record['uom_id'],
                        'is_optional': False,
                    }
                ],
            },
        )
        assert recipe_r.status_code == status.HTTP_201_CREATED, recipe_r.text
        recipe_id = recipe_r.json()['id']

        # Start a picking session (no period mutation yet).
        start_r = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            headers=auth_headers,
            json={'servings': 2},
        )
        assert start_r.status_code == status.HTTP_201_CREATED, start_r.text
        session_id = start_r.json()['picking_session_id']

        # Close the current period, then attempt the scan (the mutation).
        _close_current_period(client, auth_headers)

        resp = client.post(
            f'/api/v1/recipes/{recipe_id}/picking/{session_id}/scan',
            headers=auth_headers,
            json={'item_id': record['id']},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'PERIOD_CLOSED'
        assert 'closed' in detail['message'].lower()
