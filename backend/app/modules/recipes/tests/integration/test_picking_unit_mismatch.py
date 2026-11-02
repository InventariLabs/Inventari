"""Integration tests: picking refuses to guess across incomparable measures.

A recipe asking for 500 g and a shelf counted in pieces are not comparable
until something records what one piece weighs. Availability already reports
both readings instead of inventing a verdict; picking must not quietly take
"the whole thing" because 500 is larger than 1.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _shelf(
    db: Session,
    user: User,
    location: StorageLocation,
    *,
    weight_value: Decimal | None,
    pieces: int = 1,
) -> tuple[ProductTemplate, Item]:
    """One product counted in pieces, optionally recording what a piece weighs."""
    pcs = _uom_id(db, 'pcs')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name='Flour',
        uom_id=pcs,
        weight_value=weight_value,
        weight_uom_id=_uom_id(db, 'g') if weight_value is not None else None,
    )
    db.add(template)
    db.flush()
    item = Item(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        storage_location_id=location.id,
        name='Flour',
        template_id=template.id,
        uom_id=pcs,
        quantity=Decimal(pieces),
    )
    db.add(item)
    anchor_pending_records(db)
    db.commit()
    return template, item


def _recipe_in_grams(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    template: ProductTemplate,
    grams: str = '500',
) -> str:
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Bread',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Flour',
                    'template_id': str(template.id),
                    'quantity': grams,
                    'uom_id': str(_uom_id(db, 'g')),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _scan(
    client: TestClient,
    auth_headers: dict[str, str],
    recipe_id: str,
    item_id: uuid.UUID,
) -> dict[str, Any]:
    start = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=auth_headers,
    )
    assert start.status_code == 201, start.text
    session_id = start.json()['picking_session_id']
    scan = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
        json={'item_id': str(item_id)},
        headers=auth_headers,
    )
    assert scan.status_code == 200, scan.text
    body: dict[str, Any] = scan.json()
    return body


class TestPickingUnitMismatch:
    def test_scan_without_a_bridge_takes_nothing_and_says_why(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """500 g asked of 1 piece, with nothing saying what a piece weighs."""
        template, item = _shelf(
            db_session, test_user, test_storage_location, weight_value=None
        )
        recipe_id = _recipe_in_grams(client, auth_headers, db_session, template)

        body = _scan(client, auth_headers, recipe_id, item.id)

        assert body['status'] == 'unit_mismatch'
        assert body['quantity_consumed'] is None
        mismatch = body['unit_mismatch']
        assert mismatch['required_quantity'] == 500.0
        assert mismatch['required_uom'] == 'g'
        assert mismatch['available_quantity'] == 1.0
        assert mismatch['available_uom'] == 'pcs'

        # Nothing left the shelf.
        db_session.expire_all()
        stored = (
            db_session.execute(select(Item).where(Item.id == item.id)).scalars().first()
        )
        assert stored is not None
        assert stored.quantity == Decimal('1')

    def test_scan_with_a_bridge_consumes_the_converted_amount(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """One piece weighs 1000 g, so 500 g is half a piece — and half is taken."""
        template, item = _shelf(
            db_session,
            test_user,
            test_storage_location,
            weight_value=Decimal('1000'),
            pieces=2,
        )
        recipe_id = _recipe_in_grams(client, auth_headers, db_session, template)

        body = _scan(client, auth_headers, recipe_id, item.id)

        assert body['status'] == 'picked'
        # Progress is reported in the recipe's unit, which is what the
        # checklist counts down; the shelf gives up half a piece for it.
        assert body['quantity_consumed'] == 500.0
        assert body['uom_symbol'] == 'g'
        assert body['ingredient_remaining_quantity'] is None

        # Half a piece is part of one bag, so that bag is opened for it: the
        # sealed record gives up one unit and the open one holds what is left.
        db_session.expire_all()
        records = (
            db_session.execute(
                select(Item)
                .where(Item.template_id == template.id)
                .order_by(Item.created_at)
            )
            .scalars()
            .all()
        )
        assert [r.quantity for r in records] == [Decimal('1'), Decimal('0.500')]
        assert records[0].id == item.id
        assert records[1].meta_data is not None
        assert records[1].meta_data['opened']['at']
