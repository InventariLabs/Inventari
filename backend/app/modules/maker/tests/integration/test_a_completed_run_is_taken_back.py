"""A completed production run is taken back by the reversal it writes.

The run itself stays as it was — a completed run is immutable — and the way
back from a typo is the reversing entry beside it, the way a receipt or an
issue is undone: every ingredient goes back to the shelf, batch and date it
was taken from, the output leaves the shelf it was put on, and the moves
register shows both under the run. Only while the output stands untouched:
goods made by the run that have since left their shelf cannot be taken off
it again, and the run says so instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=f'{name} {uuid.uuid4().hex[:6]}',
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        removal_strategy='FEFO',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(
    db: Session,
    org: Organization,
    output: ProductTemplate,
    ingredients: list[tuple[ProductTemplate, str]],
) -> None:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='Plum butter',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.flush()
    for child, per_batch in ingredients:
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=output.id,
                child_template_id=child.id,
                qty_per_batch=Decimal(per_batch),
                unit='kg',
            )
        )
    db.commit()


def _on_shelf(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
    quantity: str,
    *,
    expiry: str | None = None,
    price: str = '2.00',
) -> UUID:
    body: dict[str, Any] = {
        'name': template.name,
        'location_id': str(location.id),
        'quantity': quantity,
        'purchase_price': price,
    }
    if expiry is not None:
        body['expiry_date'] = expiry
    response = client.post('/api/v1/items', headers=headers, json=body)
    assert response.status_code == 201, response.text
    assert response.json()['template_id'] == str(template.id)
    return UUID(response.json()['id'])


def _total_value(client: TestClient, headers: dict[str, str]) -> Decimal:
    """What the Products list says the warehouse is worth."""
    response = client.get('/api/v1/items/aggregates', headers=headers)
    assert response.status_code == 200, response.text
    return Decimal(str(response.json()['total_value']))


def _quantity(db: Session, item_id: UUID) -> Decimal:
    db.expire_all()
    item = db.execute(select(Item).where(Item.id == item_id)).scalar_one()
    return Decimal(item.quantity)


def _run(
    client: TestClient,
    headers: dict[str, str],
    output: ProductTemplate,
    location: StorageLocation,
    planned: str,
) -> dict[str, Any]:
    created = client.post(
        ORDERS,
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': planned,
            'output_location_id': str(location.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'{ORDERS}/{created.json()["id"]}/complete', headers=headers
    )
    assert completed.status_code == 200, completed.text
    run: dict[str, Any] = completed.json()
    return run


def _drift(client: TestClient, headers: dict[str, str]) -> tuple[int, int]:
    report = client.get('/api/v1/stats/reconciliation', headers=headers)
    assert report.status_code == 200, report.text
    body = report.json()
    return body['quant_move_drift_count'], body['layer_quant_drift_count']


@pytest.fixture
def plum_butter(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> dict[str, Any]:
    """Plums in two batches by date on one shelf, cinnamon on another."""
    plums = _template(db_session, mk_org, 'Damson Plums')
    cinnamon = _template(db_session, mk_org, 'Cinnamon')
    butter = _template(db_session, mk_org, 'Plum Butter')
    _recipe(db_session, mk_org, butter, [(plums, '2.2'), (cinnamon, '0.1')])
    return {
        'plums': plums,
        'butter': butter,
        'early_plums': _on_shelf(
            client,
            mk_auth_headers,
            plums,
            mk_input_loc,
            '3',
            expiry='2027-01-10',
        ),
        'late_plums': _on_shelf(
            client,
            mk_auth_headers,
            plums,
            mk_input_loc,
            '3',
            expiry='2027-03-01',
        ),
        'cinnamon': _on_shelf(client, mk_auth_headers, cinnamon, mk_output_loc, '1'),
    }


class TestACompletedRunIsTakenBack:
    def test_the_ingredients_return_and_the_output_leaves(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
        plum_butter: dict[str, Any],
    ) -> None:
        # 2 kg of butter eats 4.4 kg of plums — the earlier batch whole and
        # 1.4 kg of the later one — and 0.2 kg of cinnamon from another shelf.
        run = _run(client, mk_auth_headers, plum_butter['butter'], mk_output_loc, '2')
        assert _quantity(db_session, plum_butter['early_plums']) == 0
        assert _quantity(db_session, plum_butter['late_plums']) == Decimal('1.6')
        produced = UUID(run['produced_item_id'])

        response = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'REVERSED'
        # Each batch is back on its own record, not pooled on one.
        assert _quantity(db_session, plum_butter['early_plums']) == Decimal('3')
        assert _quantity(db_session, plum_butter['late_plums']) == Decimal('3')
        assert _quantity(db_session, plum_butter['cinnamon']) == Decimal('1')
        assert _quantity(db_session, produced) == 0

        moves = client.get(
            f'{ORDERS}/{run["id"]}/stock-moves', headers=mk_auth_headers
        ).json()['items']
        returned = [
            m
            for m in moves
            if m['to_location_id']
            and m['product_template_id'] == str(plum_butter['plums'].id)
        ]
        assert sorted(Decimal(m['quantity']) for m in returned) == [
            Decimal('1.4'),
            Decimal('3'),
        ]
        taken_off = [
            m
            for m in moves
            if m['from_location_id'] == str(mk_output_loc.id)
            and m['product_template_id'] == str(plum_butter['butter'].id)
        ]
        assert [Decimal(m['quantity']) for m in taken_off] == [Decimal('2')]
        assert _drift(client, mk_auth_headers) == (0, 0)

    def test_a_run_is_taken_back_once(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
        plum_butter: dict[str, Any],
    ) -> None:
        run = _run(client, mk_auth_headers, plum_butter['butter'], mk_output_loc, '1')
        first = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)
        assert first.status_code == 200, first.text

        again = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

        assert again.status_code == 400, again.text
        assert _quantity(db_session, plum_butter['early_plums']) == Decimal('3')

    def test_a_draft_has_nothing_to_take_back(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        plum_butter: dict[str, Any],
    ) -> None:
        draft = client.post(
            ORDERS,
            headers=mk_auth_headers,
            json={
                'output_template_id': str(plum_butter['butter'].id),
                'planned_qty': '1',
                'output_location_id': str(mk_output_loc.id),
            },
        ).json()

        response = client.post(
            f'{ORDERS}/{draft["id"]}/reverse', headers=mk_auth_headers
        )

        assert response.status_code == 400, response.text

    def test_output_that_has_left_its_shelf_refuses_the_reversal(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
        plum_butter: dict[str, Any],
    ) -> None:
        run = _run(client, mk_auth_headers, plum_butter['butter'], mk_output_loc, '2')
        produced = UUID(run['produced_item_id'])
        # A jar of the run's butter is used.
        used = client.patch(
            f'/api/v1/items/{produced}/quantity',
            headers=mk_auth_headers,
            json={'quantity': '1'},
        )
        assert used.status_code == 200, used.text

        response = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

        assert response.status_code == 400, response.text
        assert 'correction' in response.json()['detail']['message']
        # Nothing came back: the run stands as it was.
        assert _quantity(db_session, plum_butter['early_plums']) == 0
        detail = client.get(f'{ORDERS}/{run["id"]}', headers=mk_auth_headers)
        assert detail.json()['status'] == 'COMPLETED'

    def test_an_emptied_record_removed_since_comes_back_as_its_own(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
        plum_butter: dict[str, Any],
    ) -> None:
        run = _run(client, mk_auth_headers, plum_butter['butter'], mk_output_loc, '2')
        # The run emptied the earlier batch; somebody tidied the empty row away.
        removed = client.delete(
            f'/api/v1/items/{plum_butter["early_plums"]}', headers=mk_auth_headers
        )
        assert removed.status_code in (200, 204), removed.text

        response = client.post(f'{ORDERS}/{run["id"]}/reverse', headers=mk_auth_headers)

        assert response.status_code == 200, response.text
        db_session.expire_all()
        back = (
            db_session.execute(
                select(Item).where(
                    Item.template_id == plum_butter['plums'].id,
                    Item.storage_location_id == mk_input_loc.id,
                    Item.is_deleted.is_(False),
                )
            )
            .scalars()
            .all()
        )
        by_date = {str(item.expiry_date): Decimal(item.quantity) for item in back}
        assert by_date == {'2027-01-10': Decimal('3'), '2027-03-01': Decimal('3')}
        assert _drift(client, mk_auth_headers) == (0, 0)


@pytest.fixture
def shifting_prices(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> dict[str, Any]:
    """Plums delivered twice, the later delivery cheaper.

    The first run eats the dear delivery, the second both, so the two runs
    open cost layers of their own — 9.00 and 5.20 a jar — and which layer an
    undo drained is visible in what the warehouse is worth afterwards.
    """
    plums = _template(db_session, mk_org, 'Damson Plums')
    cinnamon = _template(db_session, mk_org, 'Cinnamon')
    butter = _template(db_session, mk_org, 'Plum Butter')
    _recipe(db_session, mk_org, butter, [(plums, '2.2'), (cinnamon, '0.1')])
    return {
        'plums': plums,
        'butter': butter,
        'dear_plums': _on_shelf(
            client,
            mk_auth_headers,
            plums,
            mk_input_loc,
            '5',
            expiry='2027-01-10',
            price='4.00',
        ),
        'cheap_plums': _on_shelf(
            client,
            mk_auth_headers,
            plums,
            mk_input_loc,
            '4',
            expiry='2027-03-01',
            price='2.00',
        ),
        'cinnamon': _on_shelf(client, mk_auth_headers, cinnamon, mk_output_loc, '1'),
    }


def _running_value(
    db_session: Session, template: ProductTemplate
) -> list[tuple[Decimal, Decimal]]:
    """Every open cost layer of *template*, as (quantity left, unit cost)."""
    db_session.expire_all()
    layers = db_session.scalars(
        select(StockValuationLayer)
        .where(
            StockValuationLayer.organization_id == template.organization_id,
            StockValuationLayer.product_template_id == template.id,
            StockValuationLayer.direction == 'IN',
            StockValuationLayer.remaining_qty > 0,
        )
        .order_by(StockValuationLayer.created_at, StockValuationLayer.id)
    ).all()
    return [
        (Decimal(layer.remaining_qty), Decimal(layer.unit_cost)) for layer in layers
    ]


class TestTheOutputComesBackAtItsOwnCost:
    def test_undoing_a_run_leaves_the_warehouse_worth_what_it_was(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
        shifting_prices: dict[str, Any],
    ) -> None:
        """The run's own layer holds what undoing it takes back off the books.

        Two runs of two jars each: the first costs 9.00 a jar, the second
        5.20, because the second eats the cheaper plum delivery too. Undoing
        the second gives its ingredients back at 10.40 and must take its
        output off at that same 10.40. Draining the product's oldest layer
        instead took 18.00 and left the warehouse worth 22.40 where it stood
        at 30.00, with every quantity back as before.
        """
        _run(client, mk_auth_headers, shifting_prices['butter'], mk_output_loc, '2')
        second = _run(
            client, mk_auth_headers, shifting_prices['butter'], mk_output_loc, '2'
        )
        before = _total_value(client, mk_auth_headers)
        assert before == Decimal('30.00')
        assert _running_value(db_session, shifting_prices['butter']) == [
            (Decimal('2'), Decimal('9.0000')),
            (Decimal('2'), Decimal('5.2000')),
        ]

        response = client.post(
            f'{ORDERS}/{second["id"]}/reverse', headers=mk_auth_headers
        )

        assert response.status_code == 200, response.text
        assert _total_value(client, mk_auth_headers) == before
        # The first run's layer still stands whole; the second's is drained.
        assert _running_value(db_session, shifting_prices['butter']) == [
            (Decimal('2'), Decimal('9.0000'))
        ]
        taken = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id
                == shifting_prices['butter'].organization_id,
                StockValuationLayer.product_template_id == shifting_prices['butter'].id,
                StockValuationLayer.direction == 'OUT',
            )
        ).all()
        assert [
            (Decimal(layer.quantity), Decimal(layer.total_value)) for layer in taken
        ] == [(Decimal('2'), Decimal('10.40'))]
        assert _drift(client, mk_auth_headers) == (0, 0)

    def test_every_portion_of_a_run_leaves_its_own_layer(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
        shifting_prices: dict[str, Any],
    ) -> None:
        """A run filled in portions gives each portion's value back.

        The run opened a layer per portion, both at 5.20. Undoing it must
        drain those two, not the older 9.00 layer of the run before it, or
        the warehouse falls by 7.60 with the quantities untouched.
        """
        _run(client, mk_auth_headers, shifting_prices['butter'], mk_output_loc, '2')
        created = client.post(
            ORDERS,
            headers=mk_auth_headers,
            json={
                'output_template_id': str(shifting_prices['butter'].id),
                'planned_qty': '2',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert created.status_code == 201, created.text
        order_id = created.json()['id']
        started = client.post(f'{ORDERS}/{order_id}/start', headers=mk_auth_headers)
        assert started.status_code == 200, started.text
        for _portion in range(2):
            posted = client.post(
                f'{ORDERS}/{order_id}/portions',
                headers=mk_auth_headers,
                json={'qty': '1'},
            )
            assert posted.status_code == 201, posted.text
        finished = client.post(
            f'{ORDERS}/{order_id}/finish',
            headers=mk_auth_headers,
            json={'actual_qty': '2'},
        )
        assert finished.status_code == 200, finished.text
        before = _total_value(client, mk_auth_headers)
        assert before == Decimal('30.00')

        response = client.post(f'{ORDERS}/{order_id}/reverse', headers=mk_auth_headers)

        assert response.status_code == 200, response.text
        assert _total_value(client, mk_auth_headers) == before
        # The older run's layer stands; the two portions' layers are empty.
        assert _running_value(db_session, shifting_prices['butter']) == [
            (Decimal('2'), Decimal('9.0000'))
        ]
        assert _drift(client, mk_auth_headers) == (0, 0)
