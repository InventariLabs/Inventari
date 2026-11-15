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
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe, MakerRecipeCostLine
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

    def add_fixed_cost(self, label: str, amount: str) -> None:
        recipe = self.db.scalars(select(MakerRecipe)).one()
        self.db.add(
            MakerRecipeCostLine(
                organization_id=recipe.organization_id,
                recipe_id=recipe.id,
                kind='other',
                label=label,
                amount=Decimal(amount),
            )
        )
        self.db.commit()

    def set_yield(self, qty: str) -> None:
        recipe = self.db.scalars(select(MakerRecipe)).one()
        recipe.batch_yield_qty = Decimal(qty)
        self.db.commit()

    def sell(self, template: ProductTemplate, qty: str) -> None:
        """Take a quantity of the product off its shelf, the way a dispatch would."""
        self.db.expire_all()
        item = self.db.scalars(
            select(Item).where(Item.template_id == template.id, Item.quantity > 0)
        ).first()
        assert item is not None
        moved = self.client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=self.headers,
            json={'quantity': qty},
        )
        assert moved.status_code == 200, moved.text

    def stock_value(self) -> float:
        value = self.client.get('/api/v1/stats/overview', headers=self.headers)
        assert value.status_code == 200, value.text
        return float(value.json()['total_value'])

    def worth_on(self, instant: datetime) -> Decimal:
        """What the as-of valuation says the warehouse was worth at *instant*."""
        report = self.client.get(
            '/api/v1/stock-as-of',
            headers=self.headers,
            params={'as_of': instant.isoformat()},
        )
        assert report.status_code == 200, report.text
        return Decimal(str(report.json()['total_value']))

    def batches(self, template: ProductTemplate) -> dict[str, str]:
        """Every batch of the product, with its state."""
        self.db.expire_all()
        return {
            lot.name: lot.status
            for lot in self.db.scalars(
                select(StockLot).where(StockLot.product_template_id == template.id)
            )
        }


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


def test_a_run_whose_portions_hold_its_whole_output_keeps_its_cost(
    winery: _Winery,
) -> None:
    # Two grapes were taken for two planned bottles but only one came out, and
    # it is already on the shelf as a portion booked at 3.00: the run's other
    # 3.00 goes on that portion when the run finishes.
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})

    finished = winery.post(order_id, 'finish', {'actual_qty': '1'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('6.00')
    assert Decimal(str(done['unit_cost'])) == Decimal('6')
    assert winery.on_shelf(winery.wine) == Decimal('1')
    assert winery.stock_value() == 30.0


def test_a_run_filled_to_its_plan_carries_its_fixed_costs_on_its_last_portion(
    winery: _Winery,
) -> None:
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('7.00')
    assert winery.on_shelf(winery.wine) == Decimal('2')
    # The two grapes left the shelf worth 6.00; the wine holds 7.00 with corks.
    assert winery.stock_value() == 31.0


def test_a_cost_that_does_not_divide_to_four_places_still_adds_up_at_the_finish(
    winery: _Winery,
) -> None:
    # One grape (3.00) for 700 bottles is 0.00428... a bottle, which the
    # portions store at four places: the portions add up to 3.01 and the
    # finish puts the cent right instead of refusing.
    winery.set_yield('700')
    order_id = winery.draft('700')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '300'})
    winery.post(order_id, 'portions', {'qty': '400'})

    finished = winery.post(order_id, 'finish', {'actual_qty': '700'})

    assert finished.status_code == 200, finished.text
    assert Decimal(str(finished.json()['total_cost'])) == Decimal('3.00')
    assert abs(winery.stock_value() - 30.0) < 0.011


def test_a_run_whose_output_has_left_the_shelf_closes_and_says_what_it_could_not_place(
    winery: _Winery,
) -> None:
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})
    winery.sell(winery.wine, '1')

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('7.00')
    # The two grapes (6.00) and the corks (1.00) cost 7.00; the bottle that is
    # still on the shelf holds its half of the run's cost, the sold one's half
    # of the corks is the part that could not go on the shelf.
    assert Decimal(str(done['unshelved_cost'])) == Decimal('0.50')
    assert winery.stock_value() == 24.0 + 3.0 + 0.5


def test_a_run_whose_output_was_all_sold_still_closes(winery: _Winery) -> None:
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})
    winery.sell(winery.wine, '1')
    winery.sell(winery.wine, '1')

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert done['status'] == 'COMPLETED'
    assert Decimal(str(done['unshelved_cost'])) == Decimal('1.00')


def test_older_unpriced_stock_of_the_output_does_not_stop_the_finish(
    winery: _Winery,
) -> None:
    # Two bottles of the same wine were entered earlier with no price. They
    # are in the cost history of the product; the run's rest of cost goes on
    # the run's own bottles, not on them, and the finish is not refused.
    post_on_shelf(winery.client, winery.headers, winery.wine, winery.cellar.id, 2)
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})

    finished = winery.post(order_id, 'finish')

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('7.00')
    assert Decimal(str(done['unshelved_cost'])) == Decimal('0.00')
    # 8 grapes left at 3.00 = 24.00, the wine of the run is worth 7.00, the
    # two older bottles carry no value.
    assert winery.stock_value() == 24.0 + 7.0


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


def test_every_batch_a_run_filled_belongs_to_the_run(winery: _Winery) -> None:
    order_id = winery.draft('3')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'WA'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'WB'})
    finished = winery.post(
        order_id, 'finish', {'actual_qty': '3', 'output_lot_name': 'WC'}
    )
    assert finished.status_code == 200, finished.text

    # The run names the batches its output went into — not one made up for it.
    detail = winery.client.get(
        f'{API}/orders/{order_id}', headers=winery.headers
    ).json()
    assert [batch['lot_name'] for batch in detail['output_batches']] == [
        'WA',
        'WB',
        'WC',
    ]
    assert detail['output_lot_name'] == 'WA'
    assert set(winery.batches(winery.wine)) == {'WA', 'WB', 'WC'}

    held = winery.post(order_id, 'hold', {'reason': 'Cloudy'})

    assert held.status_code == 200, held.text
    assert {batch['status'] for batch in held.json()['batches']} == {'quarantined'}
    assert set(winery.batches(winery.wine).values()) == {'quarantined'}
    detail = winery.client.get(
        f'{API}/orders/{order_id}', headers=winery.headers
    ).json()
    assert {batch['status'] for batch in detail['output_batches']} == {'quarantined'}

    record = winery.client.get(
        f'{API}/orders/{order_id}/record', headers=winery.headers
    )
    assert record.status_code == 200, record.text
    assert [batch['lot_name'] for batch in record.json()['output_batches']] == [
        'WA',
        'WB',
        'WC',
    ]

    released = winery.post(order_id, 'release')

    assert released.status_code == 200, released.text
    assert set(winery.batches(winery.wine).values()) == {'active'}


def test_a_run_whose_portions_name_no_batch_files_them_under_its_own(
    winery: _Winery,
) -> None:
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'finish', {'actual_qty': '2'})

    detail = winery.client.get(
        f'{API}/orders/{order_id}', headers=winery.headers
    ).json()

    names = winery.batches(winery.wine)
    assert len(names) == 1
    assert [batch['lot_name'] for batch in detail['output_batches']] == list(names)
    assert detail['output_lot_name'] == next(iter(names))


def test_the_cent_a_cost_does_not_divide_into_stays_on_a_bottle_still_there(
    winery: _Winery,
) -> None:
    # One grape (3.00) makes three bottles and the corks cost 1.00: the rest of
    # the cost, 1.00, does not split into three equal cents. Every bottle is on
    # the shelf, so the run's whole cost is in stock and none of it is said to
    # have left.
    winery.set_yield('3')
    winery.add_fixed_cost('Corks', '1.00')
    order_id = winery.draft('3')
    winery.post(order_id, 'start')
    for name in ('W1', 'W2', 'W3'):
        winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': name})

    finished = winery.post(order_id, 'finish')

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('4.00')
    assert Decimal(str(done['unshelved_cost'] or 0)) == Decimal('0')
    # 30.00 of grapes before, 3.00 of them in the wine, 4.00 the wine cost.
    assert winery.stock_value() == 31.0


def test_the_value_a_finish_adds_is_dated_from_the_finish(winery: _Winery) -> None:
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})
    before_the_finish = datetime.now(UTC)
    worth_then = winery.worth_on(before_the_finish)

    winery.post(order_id, 'finish', {'actual_qty': '2'})

    # A report about an instant before the finish says what it said then: the
    # corks' cost is not in the past.
    assert worth_then == Decimal('30.00')
    assert winery.worth_on(before_the_finish) == worth_then
    # And the shelf now holds it, in the live figure and in the report alike.
    assert winery.stock_value() == 31.0
    assert winery.worth_on(datetime.now(UTC)) == Decimal('31.00')


def test_a_run_of_unpriced_ingredients_with_a_fixed_cost_reads_alike_everywhere(
    winery: _Winery,
) -> None:
    # The grapes on the shelf were never priced, so the portions open layers
    # nobody can put a cost on; the corks are the one cost the run knows. Once
    # the finish puts it on those layers, the live figure and the report agree.
    shelf_id = winery.db.scalar(
        select(Item.location_id).where(Item.template_id == winery.grapes.id)
    )
    assert shelf_id is not None
    winery.sell(winery.grapes, '10')
    post_on_shelf(winery.client, winery.headers, winery.grapes, shelf_id, 10)
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})
    before_the_finish = datetime.now(UTC)

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    assert winery.stock_value() == 1.0
    assert winery.worth_on(datetime.now(UTC)) == Decimal('1.00')
    # Before the finish nobody could put a cost on the wine, and it still reads
    # that way: the cost the finish placed is not in the past.
    assert winery.worth_on(before_the_finish) == Decimal('0.00')


def test_unpriced_portions_do_not_borrow_the_rate_of_the_older_stock_of_the_output(
    winery: _Winery,
) -> None:
    # Garden grapes nobody priced, and two bottles of last year's wine on the
    # shelf at 5.00. The portions carry no cost of their own, so they must not
    # be valued at the rate of those older bottles: the finish would then add
    # the run's cost on top of a cost it never had. What the run cost -- the
    # corks, 1.00 -- is what ends up on its two bottles, as a one-step
    # completion posts it.
    shelf_id = winery.db.scalar(
        select(Item.location_id).where(Item.template_id == winery.grapes.id)
    )
    assert shelf_id is not None
    winery.sell(winery.grapes, '10')
    post_on_shelf(winery.client, winery.headers, winery.grapes, shelf_id, 10)
    post_on_shelf(
        winery.client,
        winery.headers,
        winery.wine,
        winery.cellar.id,
        2,
        purchase_price='5.00',
    )
    winery.add_fixed_cost('Corks', '0.50')
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W1'})
    winery.post(order_id, 'portions', {'qty': '1', 'output_lot_name': 'W2'})
    # Between the portions and the finish nobody can say what they cost.
    assert winery.stock_value() == 10.0

    finished = winery.post(order_id, 'finish', {'actual_qty': '2'})

    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert Decimal(str(done['total_cost'])) == Decimal('1.00')
    assert Decimal(str(done['unit_cost_snapshot'])) == Decimal('0.50')
    assert winery.stock_value() == 11.0
    assert winery.worth_on(datetime.now(UTC)) == Decimal('11.00')


def test_a_run_whose_portions_share_a_batch_is_taken_back(winery: _Winery) -> None:
    # Portions nobody named a batch for all go into the run's own: taking the
    # first off the shelf must not read as stock having left the batch the
    # next one is in.
    order_id = winery.draft('3')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'finish', {'actual_qty': '3'})
    assert len(winery.batches(winery.wine)) == 1

    reversed_run = winery.post(order_id, 'reverse')

    assert reversed_run.status_code == 200, reversed_run.text
    assert reversed_run.json()['status'] == 'REVERSED'
    assert winery.on_shelf(winery.wine) == Decimal('0')
    assert winery.on_shelf(winery.grapes) == Decimal('10')


def test_a_run_whose_portion_has_left_the_shelf_is_not_taken_back(
    winery: _Winery,
) -> None:
    order_id = winery.draft('2')
    winery.post(order_id, 'start')
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'portions', {'qty': '1'})
    winery.post(order_id, 'finish', {'actual_qty': '2'})
    winery.sell(winery.wine, '1')

    refused = winery.post(order_id, 'reverse')

    assert refused.status_code == 400, refused.text
    assert winery.on_shelf(winery.wine) == Decimal('1')
