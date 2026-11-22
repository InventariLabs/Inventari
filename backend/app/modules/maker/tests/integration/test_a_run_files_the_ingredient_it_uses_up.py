"""A run that uses the last of an ingredient files its record under Consumed.

The record leaves the products list like one used up by hand, and taking the
run back returns that same record to the shelf it left.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.flush()
    return template


def _candle_with_wax(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    shelf: StorageLocation,
    wax_on_hand: str,
) -> tuple[ProductTemplate, UUID]:
    wax = _template(db, org, 'Soy wax')
    candle = _template(db, org, 'Soy candle')
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=candle.id,
        name='Soy candle',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.flush()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=candle.id,
            child_template_id=wax.id,
            qty_per_batch=Decimal('1'),
            unit='pcs',
        )
    )
    db.commit()
    posted = client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': wax.name,
            'location_id': str(shelf.id),
            'quantity': wax_on_hand,
            'purchase_price': '2.00',
        },
    )
    assert posted.status_code == 201, posted.text
    return candle, UUID(posted.json()['id'])


def _complete(
    client: TestClient,
    headers: dict[str, str],
    candle: ProductTemplate,
    output_shelf: StorageLocation,
    planned: str,
) -> dict[str, str]:
    created = client.post(
        ORDERS,
        headers=headers,
        json={
            'output_template_id': str(candle.id),
            'planned_qty': planned,
            'output_location_id': str(output_shelf.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'{ORDERS}/{created.json()["id"]}/complete', headers=headers
    )
    assert completed.status_code == 200, completed.text
    run: dict[str, str] = completed.json()
    return run


def _listed(client: TestClient, headers: dict[str, str]) -> set[str]:
    listed = client.get('/api/v1/items', headers=headers).json()['items']
    return {row['id'] for row in listed}


def _record(db: Session, item_id: UUID) -> Item:
    db.expire_all()
    return db.execute(select(Item).where(Item.id == item_id)).scalar_one()


def test_the_last_of_an_ingredient_leaves_the_products_list(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    candle, wax = _candle_with_wax(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc, '3'
    )
    assert str(wax) in _listed(client, mk_auth_headers)

    _complete(client, mk_auth_headers, candle, mk_output_loc, '3')

    record = _record(db_session, wax)
    assert record.quantity == 0
    place = db_session.get(StorageLocation, record.storage_location_id)
    assert place is not None
    assert place.usage == LocationUsage.CUSTOMER
    assert str(wax) not in _listed(client, mk_auth_headers)


def test_an_ingredient_with_some_left_stays_on_its_shelf(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    candle, wax = _candle_with_wax(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc, '5'
    )

    _complete(client, mk_auth_headers, candle, mk_output_loc, '3')

    record = _record(db_session, wax)
    assert record.quantity == 2
    assert record.storage_location_id == mk_input_loc.id
    assert str(wax) in _listed(client, mk_auth_headers)


def test_taking_the_run_back_returns_the_used_up_record_to_its_shelf(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    candle, wax = _candle_with_wax(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc, '3'
    )
    run = _complete(client, mk_auth_headers, candle, mk_output_loc, '3')

    response = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

    assert response.status_code == 200, response.text
    record = _record(db_session, wax)
    assert record.quantity == 3
    assert record.storage_location_id == mk_input_loc.id
    assert not (record.meta_data or {}).get('emptied_from')
    assert str(wax) in _listed(client, mk_auth_headers)
    on_the_shelf = (
        db_session.execute(
            select(Item).where(
                Item.template_id == record.template_id,
                Item.storage_location_id == mk_input_loc.id,
                Item.is_deleted.is_(False),
            )
        )
        .scalars()
        .all()
    )
    assert [item.id for item in on_the_shelf] == [wax]
