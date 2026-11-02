"""Integration tests: picking names what is left of a partly used package.

A scanned barcode that matches the same product on two shelves asks the
picker which one to take. A pack at 0.75 pcs on a card recording 2 kg a piece
read as a bare fraction of a piece; the candidate now carries the unit it is
kept in and what one piece weighs, so the screen can say 1.5 kg left of 2 kg.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
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


def _two_shelves(
    db: Session,
    user: User,
    pantry: StorageLocation,
    *,
    weight_value: Decimal | None,
) -> ProductTemplate:
    """Flour counted in pieces on two shelves, one pack of it partly used."""
    pcs = _uom_id(db, 'pcs')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name='Flour',
        barcode='5900000000017',
        uom_id=pcs,
        weight_value=weight_value,
        weight_uom_id=_uom_id(db, 'kg') if weight_value is not None else None,
    )
    db.add(template)
    cellar = StorageLocation(
        organization_id=user.organization_id, created_by=user.id, name='Cellar'
    )
    db.add(cellar)
    db.flush()
    for shelf, quantity in ((pantry, Decimal('0.75')), (cellar, Decimal('2'))):
        db.add(
            Item(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                storage_location_id=shelf.id,
                name='Flour',
                template_id=template.id,
                uom_id=pcs,
                quantity=quantity,
            )
        )
    anchor_pending_records(db)
    db.commit()
    return template


def _scan_barcode(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    template: ProductTemplate,
) -> dict[str, Any]:
    recipe = client.post(
        RECIPE_URL,
        json={
            'name': 'Bread',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Flour',
                    'template_id': str(template.id),
                    'quantity': '1',
                    'uom_id': str(_uom_id(db, 'kg')),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    start = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=auth_headers,
    )
    assert start.status_code == 201, start.text
    session_id = start.json()['picking_session_id']
    scan = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
        json={'barcode': template.barcode},
        headers=auth_headers,
    )
    assert scan.status_code == 200, scan.text
    body: dict[str, Any] = scan.json()
    return body


class TestPickingCandidatesShowWhatIsLeft:
    def test_a_candidate_carries_its_unit_and_what_a_piece_weighs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _two_shelves(
            db_session, test_user, test_storage_location, weight_value=Decimal('2')
        )

        body = _scan_barcode(client, auth_headers, db_session, template)

        assert body['status'] == 'disambiguation_required'
        partly_used = next(c for c in body['candidates'] if c['quantity'] == 0.75)
        assert partly_used['uom_symbol'] == 'pcs'
        assert partly_used['uom_id'] == str(_uom_id(db_session, 'pcs'))
        assert partly_used['piece_measure_value'] == 2.0
        assert partly_used['piece_measure_symbol'] == 'kg'

    def test_a_card_with_no_weight_adds_no_measure(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _two_shelves(
            db_session, test_user, test_storage_location, weight_value=None
        )

        body = _scan_barcode(client, auth_headers, db_session, template)

        assert body['status'] == 'disambiguation_required'
        for candidate in body['candidates']:
            assert candidate['piece_measure_value'] is None
            assert candidate['piece_measure_symbol'] is None
