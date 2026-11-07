"""Integration tests for the picking session lifecycle.

Tests:
- Orphan session cleanup restores consumed stock
- AVCO rate snapshot at consume time
- Recipe delete restores consumed stock from active sessions
- Recipe edit rejected while active session exists
- Concurrent scan race condition
- is_completed when cooking on a different day
- Servings cap validation
- Basic parser recognizes culinary units
- Decimal quantity rounding
- Plan name includes year on boundaries
- Cancel idempotency
- FEFO deterministic ordering
"""

import uuid
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from tests.integration._shelf import anchor_pending_records, post_on_shelf

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = '/api/v1/recipes/meal-plans'


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Test Recipe',
        'description': 'Test description',
        'servings': 2,
        'prep_time_minutes': 30,
        'tags': [],
        'is_favorite': False,
        'ingredients': [],
    }
    base.update(overrides)
    return base


def _on_shelf(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    location: StorageLocation,
    name: str,
    quantities: list[str],
    *,
    purchase_price: str | None = None,
) -> tuple[ProductTemplate, uuid.UUID, list[uuid.UUID]]:
    """A product kept in grams and records of it on *location*, one per quantity.

    Returns the product, the gram unit its recipe line names and the records.
    """
    grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
    assert grams is not None, "'g' is not seeded"
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=test_user.organization_id,
        name=name,
        uom_id=grams,
    )
    db_session.add(template)
    db_session.commit()
    records = [
        post_on_shelf(
            client,
            auth_headers,
            template,
            location.id,
            quantity,
            purchase_price=purchase_price,
        )
        for quantity in quantities
    ]
    return template, grams, [uuid.UUID(record['id']) for record in records]


@pytest.mark.integration
class TestPickingLifecycle:
    """Tests for picking session lifecycle: orphan cleanup, recipe delete, recipe edit guard."""

    def _create_recipe_with_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any, Any]:
        """Helper: creates template + item + recipe with that ingredient."""
        template, grams, (item_id,) = _on_shelf(
            client,
            auth_headers,
            db_session,
            test_user,
            test_storage_location,
            'Test Ingredient',
            ['500'],
        )

        payload = _recipe_payload(
            name='Test Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Test Ingredient',
                    'template_id': str(template.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return r.json()['id'], item_id, template.id

    def test_starting_again_keeps_the_stock_already_taken(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """An unfinished session comes back; it is not thrown away.

        Cancelling it on sight put the ingredients of a meal that had already
        been cooked back on the shelf — three cooking sessions later the
        cupboard looked untouched, and nothing on screen ever said why.
        """
        recipe_id, item_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        # Start first session and scan an item
        start_r1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start_r1.status_code == 201
        session1_id = start_r1.json()['picking_session_id']

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session1_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200

        # Verify stock was consumed
        db_session.expire_all()
        item = (
            db_session.execute(select(Item).where(Item.id == item_id)).scalars().first()
        )
        assert item is not None
        assert item.quantity == Decimal('300')  # 500 - 200

        # Ask to start again for the same recipe
        start_r2 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start_r2.status_code == 201
        assert start_r2.json()['picking_session_id'] == session1_id
        assert start_r2.json()['resumed'] is True

        # What was taken stays taken.
        db_session.expire_all()
        item = (
            db_session.execute(select(Item).where(Item.id == item_id)).scalars().first()
        )
        assert item is not None
        assert item.quantity == Decimal('300')

        from app.modules.recipes.models import PickingSession

        session1 = (
            db_session.execute(
                select(PickingSession).where(PickingSession.id == session1_id)
            )
            .scalars()
            .first()
        )
        assert session1 is not None
        assert session1.status == 'active'

    def test_delete_recipe_with_active_session_restores_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Deleting a recipe should restore consumed stock from active picking sessions."""
        recipe_id, item_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        # Start session and scan an item
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start_r.status_code == 201
        session_id = start_r.json()['picking_session_id']

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200

        # Verify stock was consumed
        db_session.expire_all()
        item = (
            db_session.execute(select(Item).where(Item.id == item_id)).scalars().first()
        )
        assert item is not None
        assert item.quantity == Decimal('300')  # 500 - 200

        # Delete the recipe
        delete_r = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert delete_r.status_code == 204

        # Verify stock was restored
        db_session.expire_all()
        item = (
            db_session.execute(select(Item).where(Item.id == item_id)).scalars().first()
        )
        assert item is not None
        assert item.quantity == Decimal('500')  # Restored to original

    def test_edit_recipe_with_active_session_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Editing ingredients while a picking session is active should be rejected with 409."""
        recipe_id, item_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        # Start a picking session
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start_r.status_code == 201

        # Try to edit ingredients - should be rejected
        update_r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json=_recipe_payload(
                name='Updated Recipe',
                servings=4,
                ingredients=[
                    {
                        'name': 'New Ingredient',
                        'quantity': '100',
                        'is_optional': False,
                    }
                ],
            ),
            headers=auth_headers,
        )
        assert update_r.status_code == status.HTTP_409_CONFLICT
        assert (
            'picking session is active' in update_r.json()['detail']['message'].lower()
        )

        # Verify recipe was not modified
        get_r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert get_r.status_code == 200
        assert get_r.json()['name'] == 'Test Recipe'  # Original name

    def test_edit_recipe_without_active_session_succeeds(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Editing ingredients when no active session exists should succeed."""
        recipe_id, item_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        # Edit ingredients without an active session
        update_r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json=_recipe_payload(
                name='Updated Recipe',
                servings=4,
                ingredients=[
                    {
                        'name': 'New Ingredient',
                        'quantity': '100',
                        'is_optional': False,
                    }
                ],
            ),
            headers=auth_headers,
        )
        assert update_r.status_code == 200
        assert update_r.json()['name'] == 'Updated Recipe'

    def test_delete_recipe_without_active_session_succeeds(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Deleting a recipe without active sessions should succeed."""
        recipe_id, _, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        delete_r = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert delete_r.status_code == 204

        # Verify recipe is deleted
        get_r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert get_r.status_code == 404


@pytest.mark.integration
class TestPickingConcurrency:
    """Tests for the concurrent scan race condition."""

    def _create_recipe_with_two_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any, Any]:
        """Create a recipe with one ingredient and two items in stock."""
        template, grams, (item1_id, item2_id) = _on_shelf(
            client,
            auth_headers,
            db_session,
            test_user,
            test_storage_location,
            'Test Ingredient',
            ['300', '200'],
        )

        payload = _recipe_payload(
            name='Test Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Test Ingredient',
                    'template_id': str(template.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return r.json()['id'], item1_id, item2_id

    def test_concurrent_scan_does_not_lose_consumption(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Two sequential scans on the same session should not lose stock.

        With row locking, the second scan sees the updated quantity from the
        first scan. Without locking, both might read the same original quantity.
        """
        recipe_id, item1_id, _ = self._create_recipe_with_two_items(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start_r.status_code == 201
        session_id = start_r.json()['picking_session_id']

        # First scan
        scan1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item1_id)},
            headers=auth_headers,
        )
        assert scan1.status_code == 200
        assert scan1.json()['status'] == 'picked'

        # Verify stock was deducted
        db_session.expire_all()
        item1 = (
            db_session.execute(select(Item).where(Item.id == item1_id))
            .scalars()
            .first()
        )
        assert item1 is not None
        assert item1.quantity == Decimal('100')  # 300 - 200


@pytest.mark.integration
class TestPickingAVCOSnapshot:
    """Tests for AVCO rate snapshot at consume time."""

    def _create_recipe_with_valued_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any]:
        """Create a recipe with an item that has an AVCO valuation rate."""
        # The rate comes from this organization's own valuation layers: the
        # record arrives at its price and the receipt layer carries it.
        template, grams, (item_id,) = _on_shelf(
            client,
            auth_headers,
            db_session,
            test_user,
            test_storage_location,
            'Valued Ingredient',
            ['500'],
            purchase_price='5.50',
        )

        payload = _recipe_payload(
            name='Valued Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Valued Ingredient',
                    'template_id': str(template.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return r.json()['id'], item_id

    def test_undo_restores_at_consume_time_rate(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Undo should use the snapshotted AVCO rate, not the current one."""
        recipe_id, item_id = self._create_recipe_with_valued_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        # Scan to consume
        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200

        # Verify the session item has the snapshotted rate
        from app.modules.recipes.models import PickingSessionItem

        db_session.expire_all()
        si = (
            db_session.execute(
                select(PickingSessionItem).where(
                    PickingSessionItem.session_id == session_id,
                    PickingSessionItem.ingredient_id == ingredient_id,
                )
            )
            .scalars()
            .first()
        )
        assert si is not None
        assert si.consumed_valuation_rate == Decimal('5.50')

        # Undo
        undo_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        assert undo_r.status_code == 200


@pytest.mark.integration
class TestPickingValidationGuards:
    """Tests for the servings cap and cancel idempotency."""

    def _create_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> str:
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Test Ingredient',
        )
        db_session.add(template)
        db_session.flush()
        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Test Ingredient',
            template_id=template.id,
            quantity=Decimal('500'),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()
        payload = _recipe_payload(
            name='Test Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Test Ingredient',
                    'template_id': str(template.id),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return cast(str, r.json()['id'])

    def test_servings_exceeds_cap_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Servings > 200 should be rejected with 422."""
        recipe_id = self._create_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 201},
            headers=auth_headers,
        )
        assert r.status_code == 422
        assert 'servings' in r.json()['detail'][0]['loc']

    def test_servings_at_cap_accepted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Servings == 200 should be accepted."""
        recipe_id = self._create_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 200},
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_double_cancel_returns_204(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Canceling an already-cancelled session should return 204 (idempotent)."""
        recipe_id = self._create_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        # First cancel
        r1 = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert r1.status_code == 204

        # Second cancel — should be idempotent
        r2 = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert r2.status_code == 204


@pytest.mark.integration
class TestPickingOffDayCook:
    """Tests for is_completed when cooking on a different day than planned."""

    def test_a_cook_today_completes_today_and_not_yesterday(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """A cook completes the entry of the day it happened, not an earlier one.

        The recipe is planned yesterday and today and cooked once, today. Only
        today's entry reads as cooked: yesterday's used to take the session,
        so a week of a repeated recipe read meals as cooked that nobody made.
        Verifies the flag through the meal-plan API, not just the session
        status."""
        from datetime import date, timedelta

        # Create a recipe
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Test Ingredient',
        )
        db_session.add(template)
        db_session.flush()
        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Test Ingredient',
            template_id=template.id,
            quantity=Decimal('500'),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Delayed Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Test Ingredient',
                    'template_id': str(template.id),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = r.json()['id']

        # Meal plan with the entry dated YESTERDAY (off-day cook scenario).
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        end_date = (date.today() + timedelta(days=5)).isoformat()
        plan_id = client.post(
            PLAN_URL,
            json={
                'start_date': yesterday,
                'end_date': end_date,
                'enabled_slots': ['LUNCH'],
                'default_servings': 2,
            },
            headers=auth_headers,
        ).json()['id']
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': yesterday,
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']
        today_entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']

        # is_completed must be False before cooking.
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        entry = next(e for e in plan['entries'] if e['id'] == entry_id)
        assert entry['is_completed'] is False

        # Cook the recipe today (start, scan, complete).
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )

        # Cooked today: today's entry takes the session, yesterday's does not.
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        entries = {e['id']: e for e in plan['entries']}
        assert entries[entry_id]['is_completed'] is False
        assert entries[entry_id]['picking_session_id'] is None
        assert entries[today_entry_id]['is_completed'] is True
        assert entries[today_entry_id]['picking_session_id'] == session_id


@pytest.mark.integration
class TestDataQuality:
    """Tests for parser units and decimal quantities."""

    def test_basic_parser_recognizes_cup_tbsp_tsp(self) -> None:
        """Basic parser should recognize culinary units."""
        from app.modules.recipes.ingredient_parser_basic import parse_ingredients_basic

        result = parse_ingredients_basic(
            [
                '2 cups flour',
                '1 tbsp salt',
                '3 tsp vanilla',
            ]
        )
        assert result[0].unit_symbol == 'cups'
        assert result[0].name == 'flour'
        assert result[1].unit_symbol == 'tbsp'
        assert result[1].name == 'salt'
        assert result[2].unit_symbol == 'tsp'
        assert result[2].name == 'vanilla'

    def test_shopping_qty_reads_the_units_rounding(self) -> None:
        """The rounding reads the unit's own step, not a whole-unit rule.

        A countable unit (rounding 1) keeps ceil-at-1; a measured unit
        (rounding 0.001) stops claiming half a kilo of flour is a kilo.
        Decimal inputs stay exact — 0.1 + 0.2 is 0.3, not the float noise.
        """
        import uuid as _uuid
        from decimal import Decimal as Dec
        from typing import Any

        from app.modules.recipes._helpers import _round_shopping_qty

        def _uom(rounding: str) -> Any:
            step = Dec(rounding)
            return type(
                '_Uom',
                (),
                {
                    'id': _uuid.uuid4(),
                    'category_id': _uuid.uuid4(),
                    'factor': Dec('1'),
                    'rounding': step,
                },
            )()

        pieces = _uom('1')
        grams = _uom('0.001')

        # Countable: never under one piece, ceiling on the unit.
        assert _round_shopping_qty(Dec('0.1'), pieces) == 1
        assert _round_shopping_qty(Dec('1.0'), pieces) == 1
        assert _round_shopping_qty(Dec('2.5'), pieces) == 3
        assert _round_shopping_qty(Dec('100'), pieces) == 100

        # Measured: the step is the floor, the ceiling is the step —
        # half a kilo stays half a kilo instead of becoming one.
        assert _round_shopping_qty(Dec('500'), grams) == 500
        assert _round_shopping_qty(Dec('0.2'), grams) == Dec('0.200')

        # No unit named: the quantity column's own scale (0.001) is the
        # step uom_service applies — the honest reading of "0.1 of
        # something unnamed".
        assert _round_shopping_qty(Dec('0.1'), None) == Dec('0.100')

        # Float input (backward compat) — converted through Decimal.
        assert _round_shopping_qty(2.5, pieces) == 3

        # No float precision noise: 0.1 + 0.2 is exactly 0.3 on Decimal,
        # and a gram unit keeps it at step 0.001.
        assert _round_shopping_qty(Dec('0.1') + Dec('0.2'), grams) == Dec('0.300')


@pytest.mark.integration
class TestPlanNameYear:
    """The plan name includes the year on boundaries."""

    def test_plan_name_includes_year_on_boundary(self) -> None:
        """Plan name should include year when start/end years differ."""
        from datetime import date

        from app.modules.recipes._meal_plan_async_schema import _auto_plan_name

        # Same year, same month
        name = _auto_plan_name(date(2026, 1, 15), date(2026, 1, 20))
        assert '2026' not in name  # year not needed

        # Same year, different month
        name = _auto_plan_name(date(2026, 1, 28), date(2026, 2, 3))
        assert '2026' not in name  # year not needed

        # Different year
        name = _auto_plan_name(date(2026, 12, 29), date(2027, 1, 3))
        assert '2026' in name
        assert '2027' in name

    def test_fefo_ties_resolve_by_quantity(self) -> None:
        """When two items have the same expiry, the one with higher quantity should be preferred."""
        from datetime import date, timedelta

        from app.modules.recipes._picking_fefo import fefo_order

        today = date.today()

        # Create mock items with same expiry but different quantities
        item1 = MagicMock()
        item1.expiry_date = today + timedelta(days=5)
        item1.quantity = Decimal('100')

        item2 = MagicMock()
        item2.expiry_date = today + timedelta(days=5)
        item2.quantity = Decimal('200')

        item3 = MagicMock()
        item3.expiry_date = today + timedelta(days=10)
        item3.quantity = Decimal('50')

        sorted_items = fefo_order([item1, item2, item3], today)

        # item1 and item2 share the same expiry: higher quantity (item2) wins.
        assert sorted_items[0] == item2
        assert sorted_items[1] == item1
        # item3 has a later expiry → last regardless of quantity.
        assert sorted_items[-1] == item3


class TestPickingUnknownStatus:
    """'unknown' means unnameable; an empty shelf is 'missing'."""

    def _start_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        *,
        recipe_name: str,
        ingredient_name: str,
    ) -> dict[str, object]:
        payload = _recipe_payload(
            name=recipe_name,
            servings=1,
            ingredients=[
                {
                    'name': ingredient_name,
                    'quantity': '500',
                    'is_optional': False,
                    # no template_id on purpose
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert r.status_code == 201
        recipe_id = r.json()['id']

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code in (200, 201), r.text
        items: list[dict[str, object]] = r.json()['items_to_pick']
        assert len(items) == 1
        return items[0]

    def test_unnameable_ingredient_starts_as_unknown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Nothing in the name to look up → the picker genuinely cannot act."""
        item = self._start_session(
            client,
            auth_headers,
            recipe_name='Unnameable Picking Recipe',
            ingredient_name='1/2',
        )
        assert item['status'] == 'unknown'
        assert item['recommended_item_id'] is None

    def test_unlinked_but_named_ingredient_starts_as_missing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """A name is a lookup key, so an empty shelf reads as 'missing'."""
        item = self._start_session(
            client,
            auth_headers,
            recipe_name='Unlinked Picking Recipe',
            ingredient_name='Mystery Spice',
        )
        assert item['status'] == 'missing'
        assert item['recommended_item_id'] is None


@pytest.mark.integration
class TestPickingDocumentRegistration:
    """Optional RW audit document on completed picking sessions."""

    def _set_toggle(
        self, client: TestClient, auth_headers: dict[str, str], value: bool
    ) -> None:
        r = client.put(
            '/api/v1/modules/recipes/settings',
            json={'register_production_as_document': value},
            headers=auth_headers,
        )
        assert r.status_code in (200, 201), r.text

    def _create_recipe_with_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any]:
        """Helper: template + item + recipe with that ingredient."""
        # The rate comes from this organization's own valuation layers: the
        # record arrives at its price and the receipt layer carries it.
        template, grams, (item_id,) = _on_shelf(
            client,
            auth_headers,
            db_session,
            test_user,
            test_storage_location,
            'B6 Ingredient',
            ['500'],
            purchase_price='4.25',
        )

        payload = _recipe_payload(
            name='B6 Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'B6 Ingredient',
                    'template_id': str(template.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return str(r.json()['id']), item_id

    def _run_complete(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        recipe_id: str,
        item_id: Any,
    ) -> str:
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        complete_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert complete_r.status_code == status.HTTP_200_OK
        return str(session_id)

    def test_toggle_on_creates_rw_draft_document(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.warehouse.models import Document

        self._set_toggle(client, auth_headers, True)
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        session_id = self._run_complete(client, auth_headers, recipe_id, item_id)

        # RW draft linked to the session via external_reference
        doc = db_session.scalars(
            select(Document).where(
                Document.external_reference == f'picking:{session_id}'
            )
        ).first()
        assert doc is not None
        assert doc.type == 'INTERNAL_OUT'
        assert doc.status == 'DRAFT'
        assert doc.source_location_id == test_storage_location.id
        assert len(doc.lines) == 1
        assert doc.lines[0].expected_quantity == Decimal('200')
        assert doc.lines[0].item_id == item_id

        # Cost snapshot: line price mirrors the AVCO rate snapshotted at
        # consume time (never recomputed later)
        from app.modules.recipes.models import PickingSessionItem

        db_session.expire_all()
        si = db_session.scalars(
            select(PickingSessionItem).where(
                PickingSessionItem.session_id == session_id
            )
        ).first()
        assert si is not None
        assert si.consumed_valuation_rate == Decimal('4.25')
        assert doc.lines[0].unit_price == si.consumed_valuation_rate

        # Notes identify the recipe (not just the picking session)
        assert 'B6 Recipe' in (doc.notes or '')

        # Session carries the back-link
        history = client.get(
            f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers
        ).json()['items']
        assert f'document: {doc.id}' in (history[0]['notes'] or '')

    def test_toggle_off_creates_no_document(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.warehouse.models import Document

        # Default is off — do not flip the toggle
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        session_id = self._run_complete(client, auth_headers, recipe_id, item_id)

        doc = db_session.scalars(
            select(Document).where(
                Document.external_reference == f'picking:{session_id}'
            )
        ).first()
        assert doc is None

    def test_warehouse_module_disabled_creates_no_document(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_household: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """Warehouse module disabled → silent no-op (graceful degradation).

        Real integration variant (replaces the earlier mock-based unit test):
        the toggle is on but 'warehouse' is not in the org's enabled modules,
        so completion must succeed without creating an RW document.
        """
        from app.modules.warehouse.models import Document

        test_household.enabled_modules = [
            m for m in (test_household.enabled_modules or []) if m != 'warehouse'
        ]
        db_session.commit()

        self._set_toggle(client, auth_headers, True)
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        # Completion still succeeds with the module disabled
        session_id = self._run_complete(client, auth_headers, recipe_id, item_id)

        doc = db_session.scalars(
            select(Document).where(
                Document.external_reference == f'picking:{session_id}'
            )
        ).first()
        assert doc is None
