"""One list of needs for the planned runs of a period, and ordering what is missing.

Two bread runs in one week each need flour. The list adds them up, subtracts
what the shelf holds and what open purchase orders still expect (with their
dates), and says what is still missing. Ordering that creates a draft
purchase order per supplier from the cheapest price in the supplier's own
unit; an ingredient with a recipe of its own is proposed as a run, not
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
    ) -> None:
        db.add(
            PartnerPricelist(
                organization_id=org.id,
                partner_id=partner.id,
                product_template_id=template.id,
                unit_price=Decimal(price),
                currency='PLN',
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
