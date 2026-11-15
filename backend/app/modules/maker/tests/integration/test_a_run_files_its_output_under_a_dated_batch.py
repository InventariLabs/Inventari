"""A run files its output under a batch dated with the day it was made.

Every production tool files a run's output under a batch, and EU law makes
the batch mark non-optional for packaged food and cosmetics. A product
carries a shelf life in days; the batch a run opens carries the run's day as
its production date and a best-before of that day plus the shelf life, which
the person closing the run may change. The output record carries the same
date, so FEFO and the expiry views read made goods like received ones. A run
nobody named a batch for names its own, unique among the product's batches.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'
SHELF_LIVES = '/api/v1/maker/production/shelf-lives'


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.flush()
    return template


@pytest.fixture
def jam(
    db_session: Session,
    client: TestClient,
    mk_org: Organization,
    mk_auth_headers: dict[str, str],
    mk_input_loc: StorageLocation,
) -> dict[str, ProductTemplate]:
    """Jam made of plums, 2 per jar, with plenty of plums on the shelf."""
    plums = _template(db_session, mk_org, 'Plums')
    jam = _template(db_session, mk_org, 'Plum jam')
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=jam.id,
        name='Jar',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.flush()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=jam.id,
            child_template_id=plums.id,
            qty_per_batch=Decimal('2'),
            unit='pcs',
        )
    )
    db_session.commit()
    post_on_shelf(client, mk_auth_headers, plums, mk_input_loc.id, '100')
    return {'plums': plums, 'jam': jam}


def _made(
    client: TestClient,
    headers: dict[str, str],
    jam: ProductTemplate,
    loc: StorageLocation,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        f'{ORDERS}/made',
        headers=headers,
        json={
            'output_template_id': str(jam.id),
            'planned_qty': '4',
            'output_location_id': str(loc.id),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _set_shelf_life(
    client: TestClient, headers: dict[str, str], template: ProductTemplate, days: int
) -> None:
    response = client.put(
        f'{SHELF_LIVES}/{template.id}', headers=headers, json={'shelf_life_days': days}
    )
    assert response.status_code == 200, response.text
    assert response.json()['shelf_life_days'] == days


def test_a_product_keeps_its_shelf_life(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    jam: dict[str, ProductTemplate],
) -> None:
    # Fails without the change: the endpoints do not exist (404).
    _set_shelf_life(client, mk_auth_headers, jam['jam'], 180)

    read = client.get(f'{SHELF_LIVES}/{jam["jam"].id}', headers=mk_auth_headers)
    cleared = client.put(
        f'{SHELF_LIVES}/{jam["jam"].id}',
        headers=mk_auth_headers,
        json={'shelf_life_days': None},
    )

    assert read.json()['shelf_life_days'] == 180
    assert cleared.json()['shelf_life_days'] is None


def test_the_batch_is_dated_by_the_run_day_and_the_shelf_life(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    _set_shelf_life(client, mk_auth_headers, jam['jam'], 180)
    # A few days back, so the batch is still in date whenever the suite runs.
    made_on = date.today() - timedelta(days=3)

    run = _made(
        client,
        mk_auth_headers,
        jam['jam'],
        mk_output_loc,
        production_date=made_on.isoformat(),
        output_lot_name='J-01',
    )

    # Fails without the change: the batch carried no dates, the record none.
    db_session.expire_all()
    lot = db_session.get(StockLot, UUID(run['output_lot_id']))
    assert lot is not None
    assert lot.production_date == made_on
    assert lot.expiry_date == made_on + timedelta(days=180)
    record = db_session.get(Item, UUID(run['produced_item_id']))
    assert record is not None and record.expiry_date == made_on + timedelta(days=180)
    detail = client.get(f'{ORDERS}/{run["id"]}', headers=mk_auth_headers).json()
    assert detail['best_before'] == (made_on + timedelta(days=180)).isoformat()
    assert detail['output_lot_status'] == 'active'
    assert detail['shelf_life_days'] == 180


def test_the_person_closing_the_run_names_another_best_before(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    _set_shelf_life(client, mk_auth_headers, jam['jam'], 180)
    draft = client.post(
        ORDERS,
        headers=mk_auth_headers,
        json={
            'output_template_id': str(jam['jam'].id),
            'planned_qty': '4',
            'output_location_id': str(mk_output_loc.id),
            'production_date': '2026-11-02',
        },
    )
    assert draft.status_code == 201, draft.text

    keeps_until = date(2026, 11, 12)
    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete',
        headers=mk_auth_headers,
        json={'best_before': keeps_until.isoformat()},
    )

    assert done.status_code == 200, done.text
    assert done.json()['best_before'] == keeps_until.isoformat()
    db_session.expire_all()
    record = db_session.get(Item, UUID(done.json()['produced_item_id']))
    assert record is not None and record.expiry_date == keeps_until


def test_a_best_before_before_the_run_day_is_refused(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    response = client.post(
        f'{ORDERS}/made',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(jam['jam'].id),
            'planned_qty': '4',
            'output_location_id': str(mk_output_loc.id),
            'production_date': '2026-11-02',
            'best_before': '2026-11-01',
        },
    )

    assert response.status_code == 400, response.text
    assert '2026-11-01' in response.text


def test_a_run_nobody_named_a_batch_for_names_its_own(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    first = _made(
        client,
        mk_auth_headers,
        jam['jam'],
        mk_output_loc,
        production_date='2026-11-02',
    )
    second = _made(
        client,
        mk_auth_headers,
        jam['jam'],
        mk_output_loc,
        production_date='2026-11-02',
    )

    # Fails without the change: an unnamed run put its output unbatched.
    assert first['output_lot_name'] == '20261102-1'
    assert second['output_lot_name'] == '20261102-2'
    listed = client.get(ORDERS, headers=mk_auth_headers).json()['items']
    assert {row['output_lot_name'] for row in listed} == {'20261102-1', '20261102-2'}
    db_session.expire_all()
    record = db_session.get(Item, UUID(second['produced_item_id']))
    assert record is not None and record.lot_id == UUID(second['output_lot_id'])
    lots = client.get(
        '/api/v1/stock-lots',
        headers=mk_auth_headers,
        params={'product_template_id': str(jam['jam'].id)},
    ).json()['items']
    assert sorted(lot['name'] for lot in lots) == ['20261102-1', '20261102-2']
