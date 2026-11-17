"""One list of needs for the planned runs of a period, and ordering what is missing.

Two bread runs in one week each need flour. The list adds them up, subtracts
what the shelf holds and what open purchase orders still expect (with their
dates), and says what is still missing. Ordering that creates a draft
purchase order per supplier and currency (the organization's own currency
first) from the cheapest price in the supplier's own unit; an ingredient with a recipe of its own is proposed as a run, not
bought. With purchasing off the on-order column does not exist.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.purchase_orders.models import (
    PartnerPricelist,
    PurchaseOrder,
    PurchaseOrderLine,
)
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

_MONDAY = date.today() + timedelta(days=30)
_API = '/api/v1/maker/production'


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Bakery',
        ['core', 'items', 'locations', 'categories', 'maker', 'purchase_orders'],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='baker@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def shelf(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    return h.create_storage_location(
        org, h.create_storage_type('Pantry', 'PANTRY'), user, name='Pantry'
    )


def _template(
    db: Session, org: Organization, name: str, *, uom: Uom | None = None
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        uom_id=uom.id if uom else None,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _kg_and_bag(db: Session, org: Organization) -> tuple[Uom, Uom]:
    category = UomCategory(organization_id=org.id, name=f'Mass-{uuid.uuid4().hex[:6]}')
    db.add(category)
    db.commit()
    kg = Uom(
        organization_id=org.id,
        category_id=category.id,
        name=f'Kilogram-{uuid.uuid4().hex[:6]}',
        symbol='kg',
        factor=Decimal('1'),
        is_reference=True,
        rounding=Decimal('0.001'),
    )
    bag = Uom(
        organization_id=org.id,
        category_id=category.id,
        name=f'Bag-{uuid.uuid4().hex[:6]}',
        symbol='bag',
        factor=Decimal('25'),
        rounding=Decimal('1'),
    )
    db.add_all([kg, bag])
    db.commit()
    return kg, bag


def _recipe(
    db: Session, org: Organization, output: ProductTemplate, child: ProductTemplate
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='Standard',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=child.id,
            qty_per_batch=Decimal('1'),
            unit='kg',
        )
    )
    db.commit()
    return recipe


def _run(
    client: TestClient,
    headers: dict[str, str],
    output: ProductTemplate,
    location: StorageLocation,
    qty: str,
    day: date,
) -> dict[str, Any]:
    created = client.post(
        f'{_API}/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': qty,
            'output_location_id': str(location.id),
            'production_date': day.isoformat(),
            'confirm_shortage': True,
        },
    )
    assert created.status_code == 201, created.text
    run: dict[str, Any] = created.json()
    return run


def _on_order(
    db: Session,
    org: Organization,
    user: User,
    template: ProductTemplate,
    qty: str,
    due: date,
    number: str = 'PO-OPEN-1',
) -> None:
    order = PurchaseOrder(
        organization_id=org.id,
        number=number,
        status='CONFIRMED',
        scheduled_date=due,
        created_by=user.id,
    )
    db.add(order)
    db.commit()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=order.id,
            product_template_id=template.id,
            name=template.name,
            quantity_ordered=Decimal(qty),
        )
    )
    db.commit()


def _week(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(
        f'{_API}/needs',
        headers=headers,
        params={
            'date_from': _MONDAY.isoformat(),
            'date_to': (_MONDAY + timedelta(days=6)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestTheCombinedList:
    def _world(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db: Session,
    ) -> tuple[ProductTemplate, ProductTemplate]:
        kg, _bag = _kg_and_bag(db, org)
        flour = _template(db, org, 'Flour', uom=kg)
        bread = _template(db, org, 'Bread')
        _recipe(db, org, bread, flour)
        post_on_shelf(client, headers, flour, shelf.id, '4')
        _run(client, headers, bread, shelf, '6', _MONDAY)
        _run(client, headers, bread, shelf, '6', _MONDAY + timedelta(days=2))
        return flour, bread

    def test_it_adds_up_the_runs_and_subtracts_stock_and_what_is_on_order(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        flour, _bread = self._world(client, headers, org, shelf, db_session)
        due = _MONDAY + timedelta(days=1)
        _on_order(db_session, org, user, flour, '3', due)

        body = _week(client, headers)

        assert body['purchasing'] is True
        assert body['run_count'] == 2
        (row,) = body['rows']
        assert row['name'] == 'Flour'
        assert row['action'] == 'buy'
        assert Decimal(row['needed']) == Decimal('12')
        assert Decimal(row['in_stock']) == Decimal('4')
        assert Decimal(row['on_order']) == Decimal('3')
        assert Decimal(row['missing']) == Decimal('5')
        assert [(d['number'], d['expected_date']) for d in row['expected']] == [
            ('PO-OPEN-1', due.isoformat())
        ]

    def test_runs_before_the_period_take_their_share_of_the_shelf_first(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        flour, bread = self._world(client, headers, org, shelf, db_session)
        _run(client, headers, bread, shelf, '3', _MONDAY - timedelta(days=7))

        body = _week(client, headers)

        (row,) = body['rows']
        # Four on the shelf, three claimed by the run of the week before.
        assert Decimal(row['in_stock']) == Decimal('1')
        assert Decimal(row['missing']) == Decimal('11')

    def test_with_purchasing_off_the_on_order_column_is_absent_not_zero(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        org = h.create_org(
            'Plain Bakery', ['core', 'items', 'locations', 'categories', 'maker']
        )
        user = h.create_user(org, email='plain@example.com')
        headers = h.get_auth_headers(user)
        shelf = h.create_storage_location(
            org, h.create_storage_type('Pantry', 'PANTRY'), user, name='Pantry'
        )
        self._world(client, headers, org, shelf, db_session)

        body = _week(client, headers)

        assert body['purchasing'] is False
        (row,) = body['rows']
        assert row['on_order'] is None
        assert row['expected'] == []
        assert Decimal(row['missing']) == Decimal('8')
        ordered = client.post(
            f'{_API}/needs/order',
            headers=headers,
            json={
                'date_from': _MONDAY.isoformat(),
                'date_to': (_MONDAY + timedelta(days=6)).isoformat(),
            },
        )
        assert ordered.status_code in (403, 404), ordered.text

    def test_what_is_on_order_is_spent_once_across_periods(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        # Five coming for the first week. A run of the week after it must not
        # read the same five as its own: the earlier run spends them first,
        # as it spends the shelf.
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, bread, flour)
        _run(client, headers, bread, shelf, '5', _MONDAY)
        _run(client, headers, bread, shelf, '3', _MONDAY + timedelta(days=7))
        _on_order(db_session, org, user, flour, '5', _MONDAY)

        first = _week(client, headers)
        second = client.get(
            f'{_API}/needs',
            headers=headers,
            params={
                'date_from': (_MONDAY + timedelta(days=7)).isoformat(),
                'date_to': (_MONDAY + timedelta(days=13)).isoformat(),
            },
        ).json()

        (first_row,) = first['rows']
        assert Decimal(first_row['on_order']) == Decimal('5')
        assert Decimal(first_row['missing']) == Decimal('0')
        (row,) = second['rows']
        assert Decimal(row['on_order']) == Decimal('0')
        assert row['expected'] == []
        assert Decimal(row['missing']) == Decimal('3')

    def test_a_planned_run_of_the_intermediate_is_what_the_need_waits_for(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        post_on_shelf(client, headers, flour, shelf.id, '5')
        _run(client, headers, bread, shelf, '5', _MONDAY)
        scope = {
            'date_from': _MONDAY.isoformat(),
            'date_to': (_MONDAY + timedelta(days=6)).isoformat(),
        }

        planned = client.post(
            f'{_API}/needs/plan-intermediates', headers=headers, json=scope
        )
        again = client.post(
            f'{_API}/needs/plan-intermediates', headers=headers, json=scope
        )
        body = _week(client, headers)

        assert len(planned.json()['runs']) == 1
        assert again.json()['runs'] == []
        rows = {r['name']: r for r in body['rows']}
        assert Decimal(rows['Dough']['planned']) == Decimal('5')
        assert Decimal(rows['Dough']['missing']) == Decimal('0')
        # The dough run needs the flour once, and the shelf holds it.
        assert Decimal(rows['Flour']['needed']) == Decimal('5')
        assert Decimal(rows['Flour']['missing']) == Decimal('0')

    def test_the_run_that_makes_the_intermediate_is_not_counted_short_twice(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        post_on_shelf(client, headers, flour, shelf.id, '5')
        bread_run = _run(client, headers, bread, shelf, '5', _MONDAY)
        dough_run = _run(client, headers, dough, shelf, '5', _MONDAY)

        listed = client.get(f'{_API}/orders', headers=headers).json()['items']
        coverage = {row['id']: row['coverage'] for row in listed}

        # Five flour, five dough from it, five bread from the dough: all of it
        # is met. Bread used to explode the dough down to flour again and
        # claim the same five the dough run claims.
        assert coverage[dough_run['id']] == 'covered'
        assert coverage[bread_run['id']] == 'covered'

    def test_a_run_planned_after_its_consumer_is_no_supply_for_it(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        bread_run = _run(client, headers, bread, shelf, '5', _MONDAY)
        _run(client, headers, dough, shelf, '5', _MONDAY + timedelta(days=3))

        listed = client.get(f'{_API}/orders', headers=headers).json()['items']
        coverage = {row['id']: row['coverage'] for row in listed}
        rows = {r['name']: r for r in _week(client, headers)['rows']}

        # The dough is made three days after the bread needs it: it is no
        # supply for the bread, and the list says so as well.
        assert coverage[bread_run['id']] == 'short'
        assert Decimal(rows['Dough']['planned']) == Decimal('0')
        assert Decimal(rows['Dough']['missing']) == Decimal('5')

    def test_a_run_planned_the_same_day_counts_whatever_was_created_first(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        bread_run = _run(client, headers, bread, shelf, '5', _MONDAY)
        _run(client, headers, dough, shelf, '5', _MONDAY)

        one_run = client.get(
            f'{_API}/needs', headers=headers, params={'order_id': bread_run['id']}
        ).json()
        week = _week(client, headers)

        # Asked for the bread alone or for the whole week, the dough run of
        # the same day is what the bread waits for.
        for body in (one_run, week):
            row = {r['name']: r for r in body['rows']}['Dough']
            assert Decimal(row['planned']) == Decimal('5')
            assert Decimal(row['missing']) == Decimal('0')

    def test_a_consumer_whose_sub_assembly_comes_later_is_not_covered_by_raw_stock(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        # Flour enough for the dough is on the shelf, but the dough itself is
        # made three days after the bread needs it. The plan and the list
        # under it say the same thing: the bread waits for dough nobody makes
        # in time, and the flour belongs to the dough run.
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        post_on_shelf(client, headers, flour, shelf.id, '10')
        bread_run = _run(client, headers, bread, shelf, '5', _MONDAY)
        dough_run = _run(
            client, headers, dough, shelf, '5', _MONDAY + timedelta(days=3)
        )

        listed = {
            row['id']: row
            for row in client.get(f'{_API}/orders', headers=headers).json()['items']
        }
        rows = {r['name']: r for r in _week(client, headers)['rows']}

        assert listed[bread_run['id']]['coverage'] == 'short'
        assert [
            i['child_template_name'] for i in listed[bread_run['id']]['coverage_items']
        ] == ['Dough']
        assert listed[dough_run['id']]['coverage'] == 'covered'
        assert Decimal(rows['Dough']['missing']) == Decimal('5')
        assert Decimal(rows['Flour']['needed']) == Decimal('5')
        assert Decimal(rows['Flour']['missing']) == Decimal('0')

    def test_what_a_planned_run_makes_is_spent_once_across_periods(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        # The week before: a dough run and the bread that uses its dough, the
        # same day. This week: another bread. The earlier bread is served by
        # its own dough run, not by this week's, so planning the dough this
        # week is missing plans it once and then the line is clear.
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        post_on_shelf(client, headers, flour, shelf.id, '20')
        week_before = _MONDAY - timedelta(days=7)
        _run(client, headers, dough, shelf, '5', week_before)
        _run(client, headers, bread, shelf, '5', week_before)
        _run(client, headers, bread, shelf, '5', _MONDAY)
        scope = {
            'date_from': _MONDAY.isoformat(),
            'date_to': (_MONDAY + timedelta(days=6)).isoformat(),
        }

        before = {r['name']: r for r in _week(client, headers)['rows']}
        planned = client.post(
            f'{_API}/needs/plan-intermediates', headers=headers, json=scope
        )
        again = client.post(
            f'{_API}/needs/plan-intermediates', headers=headers, json=scope
        )
        after = {r['name']: r for r in _week(client, headers)['rows']}

        assert Decimal(before['Dough']['planned']) == Decimal('0')
        assert Decimal(before['Dough']['missing']) == Decimal('5')
        assert len(planned.json()['runs']) == 1
        assert again.json()['runs'] == []
        assert Decimal(after['Dough']['planned']) == Decimal('5')
        assert Decimal(after['Dough']['missing']) == Decimal('0')
        # Twenty flour, five for the dough of the week before: fifteen left
        # for this week's dough run, which needs five.
        assert Decimal(after['Flour']['needed']) == Decimal('5')
        assert Decimal(after['Flour']['in_stock']) == Decimal('15')

    def test_a_sub_assembly_made_fresh_in_the_run_is_needed_as_its_ingredients(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        # A make-fresh line never takes the dough from the shelf: the bread run
        # makes it itself, from flour. The list names the flour, and proposes
        # no dough run — one the line would never take dough from.
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        line = db_session.execute(
            select(BoMLine).where(BoMLine.child_template_id == dough.id)
        ).scalar_one()
        line.make_fresh = True
        db_session.commit()
        post_on_shelf(client, headers, flour, shelf.id, '10')
        post_on_shelf(client, headers, dough, shelf.id, '5')
        bread_run = _run(client, headers, bread, shelf, '5', _MONDAY)

        listed = {
            row['id']: row
            for row in client.get(f'{_API}/orders', headers=headers).json()['items']
        }
        rows = {r['name']: r for r in _week(client, headers)['rows']}

        assert listed[bread_run['id']]['coverage'] == 'covered'
        assert list(rows) == ['Flour']
        assert Decimal(rows['Flour']['needed']) == Decimal('5')
        assert Decimal(rows['Flour']['missing']) == Decimal('0')


class TestOrderingWhatIsMissing:
    def _scope(self) -> dict[str, str]:
        return {
            'date_from': _MONDAY.isoformat(),
            'date_to': (_MONDAY + timedelta(days=6)).isoformat(),
        }

    def _offer(
        self,
        db: Session,
        org: Organization,
        partner: Any,
        template: ProductTemplate,
        price: str,
        uom: Uom | None = None,
        currency: str = 'PLN',
        min_quantity: str | None = None,
    ) -> None:
        db.add(
            PartnerPricelist(
                organization_id=org.id,
                partner_id=partner.id,
                product_template_id=template.id,
                unit_price=Decimal(price),
                currency=currency,
                min_quantity=Decimal(min_quantity) if min_quantity else None,
                uom_id=uom.id if uom else None,
                valid_from=date.today() - timedelta(days=1),
            )
        )
        db.commit()

    def test_one_draft_order_per_supplier_from_the_best_price_in_its_unit(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        sugar = _template(db_session, org, 'Sugar', uom=kg)
        cake = _template(db_session, org, 'Cake')
        recipe = _recipe(db_session, org, cake, flour)
        db_session.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=cake.id,
                child_template_id=sugar.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
            )
        )
        db_session.commit()
        mill = h.create_partner(org, user, name='Mill')
        shop = h.create_partner(org, user, name='Shop')
        # Flour: 30 a 25 kg bag at the mill (1.20 a kg) beats 1.50 a kg at the shop.
        self._offer(db_session, org, mill, flour, '30.00', bag)
        self._offer(db_session, org, shop, flour, '1.50')
        # Sugar is only sold by the shop.
        self._offer(db_session, org, shop, sugar, '2.00')
        _run(client, headers, cake, shelf, '10', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body['purchase_orders']) == 2
        placed = {
            po['partner_id']: {line['name']: line for line in po['lines']}
            for po in body['purchase_orders']
        }
        mill_line = placed[str(mill.id)]['Flour']
        # Ten kilograms short, bought as one whole 25 kg bag.
        assert Decimal(mill_line['quantity']) == Decimal('1')
        assert mill_line['uom_symbol'] == 'bag'
        assert list(placed[str(shop.id)]) == ['Sugar']
        stored = db_session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.id.in_(
                    [po['purchase_order_id'] for po in body['purchase_orders']]
                )
            )
        ).scalars()
        assert {po.status for po in stored} == {'DRAFT'}

    def test_a_volume_price_the_shortage_does_not_reach_is_not_bought(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        """5 kg short is 5 kg at 3.00, not 1000 kg at the 2.00 tier."""
        kg, _bag = _kg_and_bag(db_session, org)
        oats = _template(db_session, org, 'Oats', uom=kg)
        porridge = _template(db_session, org, 'Porridge')
        _recipe(db_session, org, porridge, oats)
        mill = h.create_partner(org, user, name='Mill')
        self._offer(db_session, org, mill, oats, '3.00')
        self._offer(db_session, org, mill, oats, '2.00', min_quantity='1000')
        _run(client, headers, porridge, shelf, '5', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        assert response.status_code == 200, response.text
        (placed,) = response.json()['purchase_orders']
        assert Decimal(placed['lines'][0]['quantity']) == Decimal('5')
        order = db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == placed['purchase_order_id'])
        ).scalar_one()
        assert order.lines[0].unit_price == Decimal('3.00')

    def test_a_volume_price_is_taken_when_the_whole_order_costs_less(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        """9 kg at 3.00 is 27.00; the 10 kg tier at 2.00 is 20.00 and wins."""
        kg, _bag = _kg_and_bag(db_session, org)
        oats = _template(db_session, org, 'Oats', uom=kg)
        porridge = _template(db_session, org, 'Porridge')
        _recipe(db_session, org, porridge, oats)
        mill = h.create_partner(org, user, name='Mill')
        self._offer(db_session, org, mill, oats, '3.00')
        self._offer(db_session, org, mill, oats, '2.00', min_quantity='10')
        _run(client, headers, porridge, shelf, '9', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        (placed,) = response.json()['purchase_orders']
        assert Decimal(placed['lines'][0]['quantity']) == Decimal('10')

    def test_one_supplier_quoting_in_two_currencies_gets_an_order_for_each(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        org.currency = 'PLN'
        db_session.commit()
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        seeds = _template(db_session, org, 'Seeds', uom=kg)
        bread = _template(db_session, org, 'Bread')
        recipe = _recipe(db_session, org, bread, flour)
        db_session.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=bread.id,
                child_template_id=seeds.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
            )
        )
        db_session.commit()
        trader = h.create_partner(org, user, name='Trader')
        self._offer(db_session, org, trader, flour, '2.00')
        self._offer(db_session, org, trader, seeds, '7.00', currency='EUR')
        _run(client, headers, bread, shelf, '5', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        assert response.status_code == 200, response.text
        placed = response.json()['purchase_orders']
        assert len(placed) == 2
        # The organization's own currency first.
        orders = [
            db_session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id == po['purchase_order_id'])
            ).scalar_one()
            for po in placed
        ]
        assert [o.currency for o in orders] == ['PLN', 'EUR']
        assert [po['lines'][0]['name'] for po in placed] == ['Flour', 'Seeds']

    def test_a_quote_in_another_currency_does_not_win_on_its_number(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        """EUR 4.00 is not cheaper than PLN 5.00 just because 4 < 5.

        No rate is held, so the organization's own currency is preferred
        and the draft order is raised in the currency of the offer chosen.
        """
        org.currency = 'PLN'
        db_session.commit()
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, bread, flour)
        abroad = h.create_partner(org, user, name='Abroad')
        local = h.create_partner(org, user, name='Local')
        self._offer(db_session, org, abroad, flour, '4.00', currency='EUR')
        self._offer(db_session, org, local, flour, '5.00')
        _run(client, headers, bread, shelf, '5', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        assert response.status_code == 200, response.text
        (placed,) = response.json()['purchase_orders']
        assert placed['partner_id'] == str(local.id)
        order = db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == placed['purchase_order_id'])
        ).scalar_one()
        assert order.currency == 'PLN'
        assert order.lines[0].unit_price == Decimal('5.00')

    def test_with_no_offer_in_the_own_currency_one_foreign_currency_is_kept_whole(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        org.currency = 'PLN'
        db_session.commit()
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, bread, flour)
        dollars = h.create_partner(org, user, name='Dollars')
        euros = h.create_partner(org, user, name='Euros')
        self._offer(db_session, org, dollars, flour, '1.00', currency='USD')
        self._offer(db_session, org, euros, flour, '9.00', currency='EUR')
        _run(client, headers, bread, shelf, '5', _MONDAY)

        response = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        )

        (placed,) = response.json()['purchase_orders']
        # EUR sorts before USD: one currency is chosen whole, not the lower number.
        assert placed['partner_id'] == str(euros.id)
        order = db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == placed['purchase_order_id'])
        ).scalar_one()
        assert order.currency == 'EUR'

    def test_ordering_twice_does_not_order_what_is_already_on_order(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, bread, flour)
        self._offer(
            db_session, org, h.create_partner(org, user, name='Mill'), flour, '1.00'
        )
        _run(client, headers, bread, shelf, '5', _MONDAY)

        first = client.post(f'{_API}/needs/order', headers=headers, json=self._scope())
        second = client.post(f'{_API}/needs/order', headers=headers, json=self._scope())

        assert len(first.json()['purchase_orders']) == 1
        assert second.json()['purchase_orders'] == []

    def test_an_ingredient_with_no_supplier_stays_unplaced_without_a_shopping_list(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, bread, flour)
        _run(client, headers, bread, shelf, '5', _MONDAY)

        body = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        ).json()

        assert body['purchase_orders'] == []
        # shopping_lists is not enabled for this organization.
        assert [r['name'] for r in body['unplaced']] == ['Flour']

    def test_a_missing_intermediate_is_proposed_as_a_run_not_bought(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        headers: dict[str, str],
        org: Organization,
        user: User,
        shelf: StorageLocation,
        db_session: Session,
    ) -> None:
        kg, _bag = _kg_and_bag(db_session, org)
        flour = _template(db_session, org, 'Flour', uom=kg)
        dough = _template(db_session, org, 'Dough', uom=kg)
        bread = _template(db_session, org, 'Bread')
        _recipe(db_session, org, dough, flour)
        _recipe(db_session, org, bread, dough)
        # Even a supplier that sells dough does not make it a purchase.
        self._offer(
            db_session, org, h.create_partner(org, user, name='Mill'), dough, '1.00'
        )
        _run(client, headers, bread, shelf, '5', _MONDAY)

        body = client.post(
            f'{_API}/needs/order', headers=headers, json=self._scope()
        ).json()

        assert body['purchase_orders'] == []
        assert [(r['name'], r['action']) for r in body['to_make']] == [
            ('Dough', 'make')
        ]
        assert Decimal(body['to_make'][0]['missing']) == Decimal('5')

        planned = client.post(
            f'{_API}/needs/plan-intermediates', headers=headers, json=self._scope()
        )
        assert planned.status_code == 201, planned.text
        (run,) = planned.json()['runs']
        assert run['name'] == 'Dough'
        assert Decimal(run['planned_qty']) == Decimal('5')
        assert run['production_date'] == _MONDAY.isoformat()


class TestTheScopeOfARequest:
    def test_a_request_naming_nothing_is_refused(
        self, client: TestClient, headers: dict[str, str]
    ) -> None:
        response = client.get(f'{_API}/needs', headers=headers)

        assert response.status_code == 400, response.text

    def test_half_a_period_is_refused(
        self, client: TestClient, headers: dict[str, str]
    ) -> None:
        response = client.get(
            f'{_API}/needs',
            headers=headers,
            params={'date_from': _MONDAY.isoformat()},
        )

        assert response.status_code == 400, response.text

    def test_a_period_that_ends_before_it_starts_is_refused(
        self, client: TestClient, headers: dict[str, str]
    ) -> None:
        response = client.get(
            f'{_API}/needs',
            headers=headers,
            params={
                'date_from': _MONDAY.isoformat(),
                'date_to': (_MONDAY - timedelta(days=1)).isoformat(),
            },
        )

        assert response.status_code == 400, response.text
