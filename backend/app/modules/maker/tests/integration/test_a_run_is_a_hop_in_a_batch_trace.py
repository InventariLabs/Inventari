"""A production run leads a batch's recall trace to the batch it made.

A recall of an ingredient reaches the customers of what was made from it
only if the run's output is a batch of its own. A run names that batch
(``output_lot_name``); the output lands in it, and the trace of the
ingredient's batch follows the run there. A run taken back nets to nothing on
both sides and leaves the trace.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'


class _Bakery:
    def __init__(
        self,
        db: Session,
        org: Organization,
        shelf: StorageLocation,
        keeper: User,
        engine: AsyncEngine,
    ) -> None:
        self.flour = self._template(db, org, 'Rye flour')
        self.bread = self._template(db, org, 'Rye bread')
        recipe = MakerRecipe(
            organization_id=org.id,
            output_template_id=self.bread.id,
            name='Loaf',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db.add(recipe)
        db.flush()
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=self.bread.id,
                child_template_id=self.flour.id,
                qty_per_batch=Decimal('2'),
                unit='pcs',
            )
        )
        self.flour_lot = StockLot(
            organization_id=org.id, product_template_id=self.flour.id, name='F-01'
        )
        db.add(self.flour_lot)
        db.commit()
        lot_id = self.flour_lot.id

        async def _put(session: AsyncSession) -> None:
            await put_on_shelf(session, keeper, self.flour, shelf.id, 20, lot_id=lot_id)

        run_in_async_session(engine, _put)

    @staticmethod
    def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
        template = ProductTemplate(
            organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
        )
        db.add(template)
        db.flush()
        return template


def _bake(
    client: TestClient,
    headers: dict[str, str],
    bakery: _Bakery,
    output_loc: StorageLocation,
    lot_name: str | None,
) -> dict[str, Any]:
    made = client.post(
        f'{ORDERS}/made',
        headers=headers,
        json={
            'output_template_id': str(bakery.bread.id),
            'planned_qty': '3',
            'output_location_id': str(output_loc.id),
            'output_lot_name': lot_name,
        },
    )
    assert made.status_code in (200, 201), made.text
    return dict(made.json())


def _trace(client: TestClient, headers: dict[str, str], lot_id: UUID) -> Any:
    response = client.get(f'/api/v1/stock-lots/{lot_id}/trace', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def bakery(
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_user: User,
    async_engine_fixture: AsyncEngine,
) -> _Bakery:
    return _Bakery(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)


def test_the_output_lands_in_the_batch_the_run_named(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    bakery: _Bakery,
    db_session: Session,
) -> None:
    run = _bake(client, mk_auth_headers, bakery, mk_output_loc, '  B-01 ')

    assert run['output_lot_name'] == 'B-01'
    db_session.expire_all()
    record = db_session.get(Item, UUID(run['produced_item_id']))
    assert record is not None
    lot = db_session.get(StockLot, record.lot_id)
    assert lot is not None
    assert (lot.name, lot.product_template_id) == ('B-01', bakery.bread.id)


def test_the_ingredients_trace_follows_the_run_to_the_bread(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    bakery: _Bakery,
) -> None:
    run = _bake(client, mk_auth_headers, bakery, mk_output_loc, 'B-01')

    trace = _trace(client, mk_auth_headers, bakery.flour_lot.id)

    [hop] = trace['lots'][0]['sent']
    assert hop['reference_type'] == 'maker_production'
    assert hop['label'] == run['number']
    assert Decimal(hop['quantity']) == Decimal('6')
    [made] = hop['produced']
    assert (made['lot_name'], made['product_name']) == ('B-01', 'Rye bread')
    assert Decimal(made['quantity']) == Decimal('3')
    # The bread's own trace follows: it came in under the same run.
    bread = trace['lots'][1]
    assert bread['lot_name'] == 'B-01'
    assert [entry['label'] for entry in bread['received']] == [run['number']]


def test_a_run_without_a_batch_still_shows_where_the_ingredient_went(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    bakery: _Bakery,
) -> None:
    run = _bake(client, mk_auth_headers, bakery, mk_output_loc, None)

    trace = _trace(client, mk_auth_headers, bakery.flour_lot.id)

    # The run is still the step forward; there is just no batch to follow.
    [hop] = trace['lots'][0]['sent']
    assert hop['label'] == run['number']
    assert hop['produced'] == []
    assert len(trace['lots']) == 1


def test_a_run_taken_back_leaves_the_trace(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    bakery: _Bakery,
    db_session: Session,
) -> None:
    run = _bake(client, mk_auth_headers, bakery, mk_output_loc, 'B-01')

    reversed_ = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

    assert reversed_.status_code == 200, reversed_.text
    trace = _trace(client, mk_auth_headers, bakery.flour_lot.id)
    assert trace['lots'][0]['sent'] == []
    # The output left the batch it was put in, not the unbatched stock.
    bread_lot = db_session.scalars(
        select(StockLot).where(StockLot.product_template_id == bakery.bread.id)
    ).one()
    assert _trace(client, mk_auth_headers, bread_lot.id)['lots'][0]['received'] == []
