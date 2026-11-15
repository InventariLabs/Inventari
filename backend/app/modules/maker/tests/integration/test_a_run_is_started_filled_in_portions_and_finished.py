"""A run can be started, filled in portions and finished on different days.

Wine, cheese, beer and ferments are made over days or weeks: the grapes leave
the records the day the vat is filled, the wine is bottled over three days and
the run closes when the last bottle is. Starting takes the ingredients and
holds what they cost as work in progress; portions put output on the shelf with
their own day and batch; finishing closes the run at what the whole of it cost.
Cancelling a run that never finished gives the ingredients back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

API = '/api/v1/maker/production'


@pytest.fixture
def mk_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Winery',
        ['core', 'items', 'locations', 'categories', 'stats', 'warehouse', 'maker'],
    )


class _Winery:
    """Wine = one grape per bottle at 3.00 each, with two timed process steps."""

    def __init__(
        self,
        db: Session,
        org: Organization,
        client: TestClient,
        headers: dict[str, str],
        shelf: StorageLocation,
        cellar: StorageLocation,
    ) -> None:
        self.db = db
        self.client = client
        self.headers = headers
        self.cellar = cellar
        self.grapes = self._template(org, 'Grapes')
        self.wine = self._template(org, 'Wine')
        recipe = MakerRecipe(
            organization_id=org.id,
            output_template_id=self.wine.id,
            name='Wine',
            batch_yield_qty=Decimal('1'),
            is_default=True,
            process_steps=[
                {'text': 'Rack', 'minutes': None},
                {'text': 'Filter', 'minutes': None},
            ],
        )
        db.add(recipe)
        db.commit()
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=self.wine.id,
                child_template_id=self.grapes.id,
                qty_per_batch=Decimal('1'),
                unit='pcs',
            )
        )
        db.commit()
        post_on_shelf(client, headers, self.grapes, shelf.id, 10, purchase_price='3.00')

    def _template(self, org: Organization, name: str) -> ProductTemplate:
        template = ProductTemplate(
            organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
        )
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def on_shelf(self, template: ProductTemplate) -> Decimal:
        self.db.expire_all()
        return self.db.scalar(
            select(func.coalesce(func.sum(Item.quantity), 0)).where(
                Item.template_id == template.id,
                Item.location_id.is_not(None),
                Item.deleted_at.is_(None),
            )
        ) or Decimal('0')

    def draft(self, qty: str = '4') -> str:
        created = self.client.post(
            f'{API}/orders',
            headers=self.headers,
            json={
                'output_template_id': str(self.wine.id),
                'planned_qty': qty,
                'output_location_id': str(self.cellar.id),
                'confirm_shortage': True,
            },
        )
        assert created.status_code == 201, created.text
        return str(created.json()['id'])

    def post(
        self, order_id: str, action: str, body: dict[str, object] | None = None
    ) -> Response:
        return self.client.post(
            f'{API}/orders/{order_id}/{action}', headers=self.headers, json=body or {}
        )

    def stock_value(self) -> float:
        value = self.client.get('/api/v1/stats/overview', headers=self.headers)
        assert value.status_code == 200, value.text
        return float(value.json()['total_value'])


@pytest.fixture
def winery(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> _Winery:
    return _Winery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, mk_output_loc
    )


def test_starting_a_run_takes_its_ingredients_and_holds_their_cost(
    winery: _Winery,
) -> None:
    order_id = winery.draft()
    day = (date.today() - timedelta(days=2)).isoformat()

    started = winery.post(order_id, 'start', {'started_on': day})

    assert started.status_code == 200, started.text
    body = started.json()
    assert body['status'] == 'IN_PROGRESS'
    assert body['started_on'] == day
    assert Decimal(str(body['material_cost'])) == Decimal('12.00')
    assert [step['text'] for step in body['steps']] == ['Rack', 'Filter']
    assert all(step['done_on'] is None for step in body['steps'])
    assert [Decimal(str(line['consumed_qty'])) for line in body['lines']] == [
        Decimal('4')
    ]
    assert winery.on_shelf(winery.grapes) == Decimal('6')
    # Nothing came out yet.
    assert winery.on_shelf(winery.wine) == Decimal('0')
    assert body['actual_qty'] is None


def test_a_started_run_does_not_make_the_warehouse_worth_less(
    client: TestClient, winery: _Winery
) -> None:
    before = winery.stock_value()
    order_id = winery.draft()

    winery.post(order_id, 'start')

    assert before == 30.0
    # The ten grapes were worth 30; four left the layers, and what they cost is
    # still held by the run.
    assert winery.stock_value() == before
    on_a_day = client.get(
        '/api/v1/stock-as-of',
        headers=winery.headers,
        params={'as_of': datetime.now(UTC).isoformat()},
    )
    assert on_a_day.status_code == 200, on_a_day.text
    assert Decimal(str(on_a_day.json()['total_value'])) == Decimal('30.00')
    assert Decimal(str(on_a_day.json()['work_in_progress_value'])) == Decimal('12.00')

    # A portion carries its share of the cost into the layers: the total stays.
    winery.post(order_id, 'portions', {'qty': '1'})
    assert winery.stock_value() == before


def test_the_output_comes_in_portions_and_the_run_closes_at_its_whole_cost(
    winery: _Winery,
) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    first_day = (date.today() - timedelta(days=1)).isoformat()

    first = winery.post(
        order_id,
        'portions',
        {'qty': '1', 'made_on': first_day, 'output_lot_name': 'B1'},
    )
    second = winery.post(order_id, 'portions', {'qty': '2', 'output_lot_name': 'B2'})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert winery.on_shelf(winery.wine) == Decimal('3')
    run = second.json()
    assert run['status'] == 'IN_PROGRESS'
    assert [(p['made_on'], p['lot_name']) for p in run['portions']] == [
        (first_day, 'B1'),
        (date.today().isoformat(), 'B2'),
    ]

    finished = winery.post(order_id, 'finish', {'actual_qty': '4'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert done['status'] == 'COMPLETED'
    assert Decimal(str(done['actual_qty'])) == Decimal('4')
    assert Decimal(str(done['total_cost'])) == Decimal('12.00')
    assert Decimal(str(done['unit_cost'])) == Decimal('3')
    # The closing quantity is the one bottle left of the four.
    assert [Decimal(str(p['qty'])) for p in done['portions']] == [
        Decimal('1'),
        Decimal('2'),
        Decimal('1'),
    ]
    assert winery.on_shelf(winery.wine) == Decimal('4')
    # What the run held is on the shelf now, not in work in progress.
    assert winery.stock_value() == 30.0


def test_a_run_is_finished_on_a_later_day_with_what_it_actually_made(
    winery: _Winery,
) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    later = (date.today() - timedelta(days=1)).isoformat()

    finished = winery.post(
        order_id, 'finish', {'actual_qty': '3', 'finished_on': later}
    )

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['actual_qty'])) == Decimal('3')
    assert done['production_date'] == later
    # What the start took divided by what came out.
    assert Decimal(str(done['unit_cost'])) == Decimal('4')
    assert winery.on_shelf(winery.wine) == Decimal('3')


def test_a_run_whose_portions_hold_its_whole_output_cannot_lose_its_cost(
    winery: _Winery,
) -> None:
    # Two grapes were taken for two planned bottles but only one came out, and
    # it is already on the shelf as a portion: booked at 3.00, the run's other
    # 3.00 has nowhere to go unless the last quantity is put on the shelf by
    # the finish itself.
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})
    before = winery.stock_value()

    refused = winery.post(order_id, 'finish', {'actual_qty': '1'})

    assert refused.status_code == 400, refused.text
    assert winery.stock_value() == before


def test_the_last_bottles_put_on_the_shelf_by_the_finish_carry_the_rest_of_the_cost(
    winery: _Winery,
) -> None:
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    assert Decimal(str(finished.json()['total_cost'])) == Decimal('6.00')
    # 30.00 before the run: nothing is lost between start and finish.
    assert winery.stock_value() == 30.0


def test_a_portion_cannot_take_the_run_above_its_plan(winery: _Winery) -> None:
    order_id = winery.draft('2')
    winery.post(order_id, 'start')

    refused = winery.post(order_id, 'portions', {'qty': '3'})

    assert refused.status_code == 400, refused.text
    assert winery.on_shelf(winery.wine) == Decimal('0')


def test_a_run_cannot_finish_with_less_than_its_portions(winery: _Winery) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '3'})

    refused = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert refused.status_code == 400, refused.text
    assert winery.on_shelf(winery.wine) == Decimal('3')


def test_cancelling_a_run_in_progress_gives_its_ingredients_back(
    winery: _Winery,
) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    assert winery.on_shelf(winery.grapes) == Decimal('6')

    cancelled = winery.post(order_id, 'cancel', {'reason': 'vat spoiled'})

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['status'] == 'CANCELLED'
    assert winery.on_shelf(winery.grapes) == Decimal('10')
    assert winery.stock_value() == 30.0


def test_a_run_with_portions_is_finished_not_cancelled(winery: _Winery) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})

    refused = winery.post(order_id, 'cancel')

    assert refused.status_code == 400, refused.text
    assert winery.on_shelf(winery.grapes) == Decimal('6')


def test_a_step_is_ticked_with_its_day(winery: _Winery) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    day = (date.today() - timedelta(days=1)).isoformat()

    ticked = winery.client.put(
        f'{API}/orders/{order_id}/steps/1',
        headers=winery.headers,
        json={'done_on': day},
    )

    assert ticked.status_code == 200, ticked.text
    assert [step['done_on'] for step in ticked.json()['steps']] == [None, day]
    missing = winery.client.put(
        f'{API}/orders/{order_id}/steps/5',
        headers=winery.headers,
        json={'done_on': day},
    )
    assert missing.status_code == 400


def test_the_steps_of_a_run_in_progress_cannot_be_ticked_on_a_draft(
    winery: _Winery,
) -> None:
    order_id = winery.draft()

    ticked = winery.client.put(
        f'{API}/orders/{order_id}/steps/0',
        headers=winery.headers,
        json={'done_on': date.today().isoformat()},
    )

    assert ticked.status_code == 400


def test_only_a_draft_is_started_and_only_a_started_run_is_finished(
    winery: _Winery,
) -> None:
    order_id = winery.draft()

    assert winery.post(order_id, 'finish').status_code == 400
    assert winery.post(order_id, 'start').status_code == 200
    assert winery.post(order_id, 'start').status_code == 400


def test_ingredients_a_run_took_are_not_available_to_another(
    winery: _Winery,
) -> None:
    first = winery.draft('8')
    winery.post(first, 'start')
    second = winery.draft('4')

    refused = winery.post(second, 'start')

    # Two of the ten grapes are left, and the second run needs four.
    assert refused.status_code == 422, refused.text
    assert winery.on_shelf(winery.grapes) == Decimal('2')


def test_a_started_run_is_work_to_do_until_it_is_finished(
    client: TestClient, winery: _Winery
) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')

    def states() -> list[str]:
        todo = client.get(
            '/api/v1/warehouse/todo',
            headers=winery.headers,
            params={'date_to': date.today().isoformat(), 'limit': 50},
        )
        assert todo.status_code == 200, todo.text
        return [
            item['state']
            for item in todo.json()['work_items']['items']
            if item['source_id'] == order_id
        ]

    assert states() == ['in_progress']
    winery.post(order_id, 'finish')
    assert states() == []


def test_a_finished_run_with_portions_is_taken_back_portion_by_portion(
    winery: _Winery,
) -> None:
    order_id = winery.draft()
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'B1'})
    winery.post(order_id, 'portions', {'qty': '2', 'output_lot_name': 'B2'})
    winery.post(order_id, 'finish', {'actual_qty': '4'})
    assert winery.on_shelf(winery.wine) == Decimal('4')

    reversed_run = winery.post(order_id, 'reverse')

    assert reversed_run.status_code == 200, reversed_run.text
    assert reversed_run.json()['status'] == 'REVERSED'
    assert winery.on_shelf(winery.wine) == Decimal('0')
    assert winery.on_shelf(winery.grapes) == Decimal('10')
