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
) -> UUID:
    body: dict[str, Any] = {
        'name': template.name,
        'location_id': str(location.id),
        'quantity': quantity,
        'purchase_price': '2.00',
    }
    if expiry is not None:
        body['expiry_date'] = expiry
    response = client.post('/api/v1/items', headers=headers, json=body)
    assert response.status_code == 201, response.text
    assert response.json()['template_id'] == str(template.id)
    return UUID(response.json()['id'])


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
