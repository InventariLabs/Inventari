"""A run takes its ingredients from the batches the person chose.

Before closing a run the person sees which batch each ingredient will be
taken from — FEFO by default, earliest best-before first — and may pick
another batch, from the list or by scanning its label. The run then takes
exactly the batches chosen, in the quantities chosen, and its movements name
them. A held batch is offered to nobody, and the run's own output batch can
be put on hold from the run and released later.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'
PLAN = '/api/v1/maker/production/ingredient-batches'


class _Kitchen:
    """Honey in two batches — an early and a late best-before — for mead."""

    def __init__(
        self,
        db: Session,
        org: Organization,
        shelf: StorageLocation,
        keeper: User,
        engine: AsyncEngine,
    ) -> None:
        self.honey = self._template(db, org, 'Honey', removal_strategy='FEFO')
        self.mead = self._template(db, org, 'Mead')
        recipe = MakerRecipe(
            organization_id=org.id,
            output_template_id=self.mead.id,
            name='Mead',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db.add(recipe)
        db.flush()
        self.recipe = recipe
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=self.mead.id,
                child_template_id=self.honey.id,
                qty_per_batch=Decimal('3'),
                unit='pcs',
            )
        )
        self.early = StockLot(
            organization_id=org.id,
            product_template_id=self.honey.id,
            name='H-EARLY',
            expiry_date=date(2027, 1, 1),
        )
        self.late = StockLot(
            organization_id=org.id,
            product_template_id=self.honey.id,
            name='H-LATE',
            expiry_date=date(2028, 1, 1),
        )
        db.add_all([self.early, self.late])
        db.commit()
        early_id, late_id = self.early.id, self.late.id

        async def _put(session: AsyncSession) -> None:
            await put_on_shelf(
                session, keeper, self.honey, shelf.id, 10, lot_id=early_id
            )
            await put_on_shelf(
                session, keeper, self.honey, shelf.id, 10, lot_id=late_id
            )

        run_in_async_session(engine, _put)

    @staticmethod
    def _template(
        db: Session, org: Organization, name: str, removal_strategy: str = 'FIFO'
    ) -> ProductTemplate:
        template = ProductTemplate(
            organization_id=org.id,
            name=name,
            sku=f'SKU-{uuid.uuid4().hex[:8]}',
            removal_strategy=removal_strategy,
        )
        db.add(template)
        db.flush()
        return template


@pytest.fixture
def kitchen(
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_user: User,
    async_engine_fixture: AsyncEngine,
) -> _Kitchen:
    return _Kitchen(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)


def _run(kitchen: _Kitchen, loc: StorageLocation, qty: str = '2') -> dict[str, Any]:
    return {
        'output_template_id': str(kitchen.mead.id),
        'planned_qty': qty,
        'output_location_id': str(loc.id),
    }


def _taken(
    client: TestClient, headers: dict[str, str], order_id: str, honey_id: uuid.UUID
) -> dict[str, Decimal]:
    moves = client.get(f'{ORDERS}/{order_id}/stock-moves', headers=headers).json()
    taken: dict[str, Decimal] = {}
    for move in moves['items']:
        if move['product_template_id'] == str(honey_id) and move['from_location_id']:
            taken[move['lot_code']] = taken.get(
                move['lot_code'], Decimal('0')
            ) + Decimal(move['quantity'])
    return taken


def test_the_plan_shows_the_fefo_batch_and_every_batch_on_offer(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    # Fails without the change: the endpoint does not exist.
    response = client.get(
        PLAN, headers=mk_auth_headers, params=_run(kitchen, mk_output_loc)
    )

    assert response.status_code == 200, response.text
    [honey] = response.json()['ingredients']
    assert Decimal(honey['needed']) == Decimal('6')
    assert [(p['lot_name'], Decimal(p['quantity'])) for p in honey['plan']] == [
        ('H-EARLY', Decimal('6'))
    ]
    assert [b['lot_name'] for b in honey['batches']] == ['H-EARLY', 'H-LATE']


def test_completion_takes_exactly_the_batch_chosen(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    draft = client.post(
        ORDERS, headers=mk_auth_headers, json=_run(kitchen, mk_output_loc)
    )
    assert draft.status_code == 201, draft.text

    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete',
        headers=mk_auth_headers,
        json={
            'ingredient_lots': [
                {
                    'template_id': str(kitchen.honey.id),
                    'lot_id': str(kitchen.late.id),
                    'quantity': '6',
                }
            ]
        },
    )

    # Fails without the change: the choice was ignored and FEFO took H-EARLY.
    assert done.status_code == 200, done.text
    assert _taken(client, mk_auth_headers, draft.json()['id'], kitchen.honey.id) == {
        'H-LATE': Decimal('6')
    }


def test_a_run_recorded_as_made_takes_the_batches_chosen_in_their_parts(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    made = client.post(
        f'{ORDERS}/made',
        headers=mk_auth_headers,
        json={
            **_run(kitchen, mk_output_loc),
            'ingredient_lots': [
                {
                    'template_id': str(kitchen.honey.id),
                    'lot_id': str(kitchen.late.id),
                    'quantity': '4',
                },
                {
                    'template_id': str(kitchen.honey.id),
                    'lot_id': str(kitchen.early.id),
                    'quantity': '2',
                },
            ],
        },
    )

    assert made.status_code == 201, made.text
    assert _taken(client, mk_auth_headers, made.json()['id'], kitchen.honey.id) == {
        'H-LATE': Decimal('4'),
        'H-EARLY': Decimal('2'),
    }


def test_a_choice_that_does_not_add_up_is_refused(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    draft = client.post(
        ORDERS, headers=mk_auth_headers, json=_run(kitchen, mk_output_loc)
    )

    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete',
        headers=mk_auth_headers,
        json={
            'ingredient_lots': [
                {
                    'template_id': str(kitchen.honey.id),
                    'lot_id': str(kitchen.late.id),
                    'quantity': '5',
                }
            ]
        },
    )

    assert done.status_code == 400, done.text
    assert 'Honey' in done.text
    assert (
        client.get(f'{ORDERS}/{draft.json()["id"]}', headers=mk_auth_headers).json()[
            'status'
        ]
        == 'DRAFT'
    )


def test_a_batch_that_cannot_give_the_choice_is_refused(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    draft = client.post(
        ORDERS, headers=mk_auth_headers, json=_run(kitchen, mk_output_loc, qty='4')
    )

    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete',
        headers=mk_auth_headers,
        json={
            'ingredient_lots': [
                {
                    'template_id': str(kitchen.honey.id),
                    'lot_id': str(kitchen.early.id),
                    'quantity': '12',
                }
            ]
        },
    )

    assert done.status_code == 400, done.text
    assert 'H-EARLY' in done.text


def test_a_held_output_batch_is_offered_to_no_other_run(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
    db_session: Session,
    mk_org: Organization,
) -> None:
    # Mead is bought in as well as made, so its formula is a variant, not
    # the product's default: a run that uses mead takes it off the shelf
    # rather than making it on the way.
    kitchen.recipe.is_default = False
    db_session.commit()
    made = client.post(
        f'{ORDERS}/made',
        headers=mk_auth_headers,
        json={
            **_run(kitchen, mk_output_loc),
            'recipe_id': str(kitchen.recipe.id),
            'output_lot_name': 'M-01',
        },
    )
    assert made.status_code == 201, made.text
    order_id = made.json()['id']
    spiced = _Kitchen._template(db_session, mk_org, 'Spiced mead')
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=spiced.id,
        name='Spiced',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.flush()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=spiced.id,
            child_template_id=kitchen.mead.id,
            qty_per_batch=Decimal('1'),
            unit='pcs',
        )
    )
    db_session.commit()

    # Fails without the change: there is no hold on the run.
    held = client.post(
        f'{ORDERS}/{order_id}/hold',
        headers=mk_auth_headers,
        json={'reason': 'Cloudy — waiting for the lab'},
    )

    assert held.status_code == 200, held.text
    assert held.json()['status'] == 'quarantined'
    detail = client.get(f'{ORDERS}/{order_id}', headers=mk_auth_headers).json()
    assert detail['output_lot_status'] == 'quarantined'
    spiced_run = {
        'output_template_id': str(spiced.id),
        'planned_qty': '1',
        'output_location_id': str(mk_output_loc.id),
    }
    plan = client.get(PLAN, headers=mk_auth_headers, params=spiced_run).json()[
        'ingredients'
    ][0]
    assert plan['plan'] == [] and plan['batches'] == []
    draft = client.post(
        ORDERS, headers=mk_auth_headers, json={**spiced_run, 'confirm_shortage': True}
    )
    refused = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete', headers=mk_auth_headers
    )
    # Refused, whatever the words: the batch on hold is not taken.
    assert refused.status_code >= 400, refused.text
    assert (
        client.get(f'{ORDERS}/{draft.json()["id"]}', headers=mk_auth_headers).json()[
            'status'
        ]
        == 'DRAFT'
    )

    released = client.post(f'{ORDERS}/{order_id}/release', headers=mk_auth_headers)

    assert released.status_code == 200, released.text
    assert released.json()['status'] == 'active'
    done = client.post(
        f'{ORDERS}/{draft.json()["id"]}/complete', headers=mk_auth_headers
    )
    assert done.status_code == 200, done.text


def test_holding_a_run_that_made_no_batch_is_refused(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    kitchen: _Kitchen,
) -> None:
    draft = client.post(
        ORDERS, headers=mk_auth_headers, json=_run(kitchen, mk_output_loc)
    )

    held = client.post(
        f'{ORDERS}/{draft.json()["id"]}/hold',
        headers=mk_auth_headers,
        json={'reason': 'not made yet'},
    )

    assert held.status_code == 400, held.text
