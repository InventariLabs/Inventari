"""A run recorded for a past day posts its stock and value on that day.

The day a person names for a run is the day its goods were made, so the
batch, the movements off and onto the shelf and the layers on the cost ledger
all carry it. Dated by the instant of recording instead, the stock on the day
before holds a batch whose record says it was made earlier, and the day's
value movement misses both the output and the ingredients it ate.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'


@pytest.fixture
def jam(
    db_session: Session,
    client: TestClient,
    mk_org: Organization,
    mk_auth_headers: dict[str, str],
    mk_input_loc: StorageLocation,
) -> dict[str, ProductTemplate]:
    """Jam made of plums, 2 per jar, with plums on the shelf."""

    def template(name: str) -> ProductTemplate:
        row = ProductTemplate(
            organization_id=mk_org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
        )
        db_session.add(row)
        db_session.flush()
        return row

    plums, product = template('Plums'), template('Plum jam')
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=product.id,
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
            parent_template_id=product.id,
            child_template_id=plums.id,
            qty_per_batch=Decimal('2'),
            unit='pcs',
        )
    )
    db_session.commit()
    post_on_shelf(client, mk_auth_headers, plums, mk_input_loc.id, '100')
    return {'plums': plums, 'jam': product}


def _complete(
    client: TestClient,
    headers: dict[str, str],
    product: ProductTemplate,
    loc: StorageLocation,
    made_on: date | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'output_template_id': str(product.id),
        'planned_qty': '4',
        'output_location_id': str(loc.id),
    }
    draft = client.post(ORDERS, headers=headers, json=body)
    assert draft.status_code == 201, draft.text
    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete',
        headers=headers,
        json={'made_on': made_on.isoformat()} if made_on else {},
    )
    assert done.status_code == 200, done.text
    return dict(done.json())


def _move_days(db: Session, run_id: str) -> set[date]:
    db.expire_all()
    moves = db.scalars(select(StockMove).where(StockMove.reference_id == UUID(run_id)))
    return {move.completed_at.date() for move in moves if move.completed_at}


def _layers(
    db: Session, product: ProductTemplate, direction: str
) -> list[StockValuationLayer]:
    return list(
        db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == product.id,
                StockValuationLayer.direction == direction,
            )
        )
    )


def test_a_back_dated_run_moves_its_goods_on_the_named_day(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    made_on = date.today() - timedelta(days=3)

    run = _complete(client, mk_auth_headers, jam['jam'], mk_output_loc, made_on)

    # Fails without the change: every movement and layer carries the day it was
    # written, so the dates below are today's.
    assert _move_days(db_session, run['id']) == {made_on}
    (output,) = _layers(db_session, jam['jam'], 'IN')
    (ate,) = _layers(db_session, jam['plums'], 'OUT')
    assert output.document_date == made_on
    assert ate.document_date == made_on


def test_a_run_recorded_for_today_is_dated_by_its_recording(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: dict[str, ProductTemplate],
) -> None:
    run = _complete(client, mk_auth_headers, jam['jam'], mk_output_loc, None)

    assert _move_days(db_session, run['id']) == {date.today()}
    (output,) = _layers(db_session, jam['jam'], 'IN')
    (ate,) = _layers(db_session, jam['plums'], 'OUT')
    assert output.document_date is None
    assert ate.document_date is None
