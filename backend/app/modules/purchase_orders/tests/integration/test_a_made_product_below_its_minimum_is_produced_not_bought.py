"""A product the organization makes, below its minimum, is produced — not bought.

A product with a recipe of its own is not bought while production is on.
The alert says to make it: no supplier is proposed, no draft order is raised for it, and To do
carries a production task that opens the production screen on the product.
With production off nothing is made here and the shortage is a purchase.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.purchase_orders.models import ReorderRule
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

_LATER = (date.today() + timedelta(days=365)).isoformat()


def _world(
    h: ModuleTestHelper, db: Session, *, modules: list[str]
) -> tuple[Any, Any, Any, Any, dict[str, str]]:
    org = h.create_org('Bakery', modules)
    user = h.create_user(org, email=f'b{uuid.uuid4().hex[:6]}@example.com')
    location = h.create_storage_location(
        org, h.create_storage_type('Shelf', 'SHELF'), user, name='Shelf'
    )
    flour = h.create_template(org, name='Flour', sku=f'F-{uuid.uuid4().hex[:6]}')
    bread = h.create_template(org, name='Bread', sku=f'B-{uuid.uuid4().hex[:6]}')
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=bread.id,
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
            parent_template_id=bread.id,
            child_template_id=flour.id,
            qty_per_batch=Decimal('1'),
            unit='pcs',
        )
    )
    db.add(
        ReorderRule(
            organization_id=org.id,
            product_template_id=bread.id,
            storage_location_id=location.id,
            min_quantity=Decimal('10'),
            max_quantity=Decimal('20'),
            safety_stock=Decimal('0'),
        )
    )
    db.commit()
    return org, bread, location, user, h.get_auth_headers(user)


def _alerts(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get(
        '/api/v1/purchase-orders/replenishment/alerts', headers=headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(list[dict[str, Any]], response.json()['items'])


class TestAMadeProductBelowItsMinimum:
    def test_the_alert_says_make_it_and_proposes_no_supplier(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        _org, bread, location, _user, headers = _world(
            h,
            db_session,
            modules=[
                'core',
                'items',
                'locations',
                'warehouse',
                'maker',
                'purchase_orders',
            ],
        )
        post_on_shelf(client, headers, bread, location.id, '3')

        (alert,) = _alerts(client, headers)

        assert alert['make_instead'] is True
        assert alert['preferred_partner_id'] is None

    def test_no_draft_order_is_raised_for_it(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        org, bread, location, _user, headers = _world(
            h,
            db_session,
            modules=[
                'core',
                'items',
                'locations',
                'warehouse',
                'maker',
                'purchase_orders',
            ],
        )
        post_on_shelf(client, headers, bread, location.id, '3')
        rule = db_session.query(ReorderRule).filter_by(organization_id=org.id).one()

        response = client.post(
            '/api/v1/purchase-orders/replenishment/draft-pos',
            headers=headers,
            json={'reorder_rule_ids': [str(rule.id)]},
        )

        body = response.json()
        assert body['created'] == []
        assert [s['reason'] for s in body['skipped']] == ['made_here']

    def test_to_do_carries_a_production_task_for_the_missing_quantity(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        _org, bread, location, _user, headers = _world(
            h,
            db_session,
            modules=[
                'core',
                'items',
                'locations',
                'warehouse',
                'maker',
                'purchase_orders',
            ],
        )
        post_on_shelf(client, headers, bread, location.id, '3')

        response = client.get(
            '/api/v1/warehouse/todo',
            headers=headers,
            params={'date_to': _LATER, 'limit': 50},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        items = [
            i
            for i in response.json()['work_items']['items']
            if i['source_kind'] == 'production_proposal'
        ]
        assert len(items) == 1
        task = items[0]
        assert (task['kind'], task['subject']) == ('produce', 'Bread')
        # Maximum 20, three on the shelf: seventeen to make.
        assert Decimal(str(task['count'])) == Decimal('17')
        assert task['action_href'] == (f'/maker/production?plan={bread.id}&quantity=17')

    def test_with_production_off_it_is_a_purchase_as_before(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        _org, bread, location, _user, headers = _world(
            h,
            db_session,
            modules=['core', 'items', 'locations', 'warehouse', 'purchase_orders'],
        )
        post_on_shelf(client, headers, bread, location.id, '3')

        (alert,) = _alerts(client, headers)
        todo = client.get(
            '/api/v1/warehouse/todo',
            headers=headers,
            params={'date_to': _LATER, 'limit': 50},
        ).json()

        assert alert['make_instead'] is False
        assert not [
            i
            for i in todo['work_items']['items']
            if i['source_kind'] == 'production_proposal'
        ]
