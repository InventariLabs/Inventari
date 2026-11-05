"""The records' view says what the records and the reservation rows say.

``stock_quants_from_records`` sums the live records of each product, shelf,
batch and owner, and the reservation rows of each, into the columns the quant
table had. It stood beside the table to be compared with it, and the
reconciliation's fourth pair was the comparison; the table is gone
(archived ``quantdrop01``) and the view is what every reader of stock reads. These pin
what it says on its own:

- it has the columns its model declares, so a reader of the model reads it;
- a day of ordinary use through the application leaves it holding what the
  day left, per product and shelf — here a household's;
- a group's reservation is the sum of its rows.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_quants_from_records import stock_quants_from_records
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from tests.integration._holds import hold
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration

_COLUMNS = text(
    'SELECT column_name FROM information_schema.columns '
    "WHERE table_schema = 'public' AND table_name = :relation "
    'ORDER BY column_name'
)


def test_the_view_has_the_columns_its_model_declares(db_session: Session) -> None:
    view = db_session.execute(_COLUMNS, {'relation': 'stock_quants_from_records'}).all()

    assert view
    assert sorted(stock_quants_from_records.c.keys()) == [row[0] for row in view]


@pytest.fixture
def pantry(
    db_session: Session, test_user: User, test_storage_type_fridge: StorageType
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        storage_type_id=test_storage_type_fridge.id,
        name='Pantry',
    )
    db_session.add(shelf)
    db_session.commit()
    return shelf


def _on_the_shelves(
    db: Session, org_id: uuid.UUID
) -> dict[tuple[str, uuid.UUID], Decimal]:
    """What the view holds per product name and shelf."""
    rows = db.execute(
        select(
            ProductTemplate.name,
            ShelfRow.storage_location_id,
            func.sum(ShelfRow.quantity),
        )
        .select_from(ShelfRow)
        .join(ProductTemplate, ProductTemplate.id == ShelfRow.product_template_id)
        .where(ShelfRow.organization_id == org_id)
        .group_by(ProductTemplate.name, ShelfRow.storage_location_id)
    ).all()
    return {(name, shelf): total for name, shelf, total in rows}


def test_a_household_day_leaves_the_view_holding_what_the_day_left(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_household: Organization,
    test_storage_location: StorageLocation,
    pantry: StorageLocation,
) -> None:
    """The same yoghurt bought again with another date, eaten, one moved."""
    today = date.today()
    records = []
    for name, qty, days in (
        ('Yoghurt', 4, 5),
        ('Yoghurt', 3, 12),
        ('Butter', 2, 40),
    ):
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': name,
                'location_id': str(test_storage_location.id),
                'quantity': qty,
                'expiry_date': str(today + timedelta(days=days)),
            },
        )
        assert created.status_code == 201, created.text
        records.append(created.json()['id'])
    first_yoghurt, _, butter = records

    eaten = client.patch(
        f'/api/v1/items/{first_yoghurt}/consume',
        headers=auth_headers,
        json={'quantity': 1},
    )
    assert eaten.status_code == 200, eaten.text
    moved = client.patch(
        f'/api/v1/items/{butter}/move',
        headers=auth_headers,
        json={'to_location_id': str(pantry.id)},
    )
    assert moved.status_code == 200, moved.text

    db_session.expire_all()
    assert _on_the_shelves(db_session, test_household.id) == {
        ('Yoghurt', test_storage_location.id): Decimal('6'),
        ('Butter', pantry.id): Decimal('2'),
    }


def test_the_view_counts_a_reservation_from_its_row(
    db_session: Session,
    test_household: Organization,
    test_storage_location: StorageLocation,
) -> None:
    org_id = test_household.id
    template = ProductTemplate(
        organization_id=org_id, name='Flour', sku=f'FL-{uuid.uuid4().hex[:8]}'
    )
    db_session.add(template)
    db_session.flush()
    lot = StockLot(organization_id=org_id, product_template_id=template.id, name='B-01')
    db_session.add(lot)
    db_session.flush()
    db_session.add(
        Item(
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            template_id=template.id,
            name='Flour',
            quantity=Decimal('10'),
            lot_id=lot.id,
        )
    )
    anchor_pending_records(db_session)
    db_session.commit()

    def grain() -> ShelfRow:
        return db_session.scalars(
            select(ShelfRow).where(ShelfRow.product_template_id == template.id)
        ).one()

    assert grain().reserved_quantity == Decimal('0')

    hold(db_session, grain(), Decimal('3'))
    hold(db_session, grain(), Decimal('2'))
    db_session.commit()

    held = grain()
    assert held.lot_id == lot.id
    assert held.quantity == Decimal('10')
    assert held.reserved_quantity == Decimal('5'), 'the sum of the two rows'
    assert held.available_quantity == Decimal('5')
