"""A reorder proposal does not propose again what is already on its way.

A product below its minimum stays alerted — the shelf is short — but what
open purchase orders still expect of a bought product, and what unfinished
runs will still make of a made one, is no longer part of what to buy or to
make. The draft-order button orders only the rest, so the same proposal
acted on twice does not order twice.
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

ALERTS = '/api/v1/purchase-orders/replenishment/alerts'
DRAFTS = '/api/v1/purchase-orders/replenishment/draft-pos'


def _later() -> str:
    return (date.today() + timedelta(days=365)).isoformat()


def _rule(
    db: Session, org: Any, template: Any, location: Any, partner_id: Any = None
) -> ReorderRule:
    rule = ReorderRule(
        organization_id=org.id,
        product_template_id=template.id,
        storage_location_id=location.id,
        min_quantity=Decimal('10'),
        max_quantity=Decimal('20'),
        safety_stock=Decimal('0'),
        preferred_partner_id=partner_id,
    )
    db.add(rule)
    db.commit()
    return rule


def _alert(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(ALERTS, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    (alert,) = response.json()['items']
    return cast(dict[str, Any], alert)


def _drafts(
    client: TestClient, headers: dict[str, str], rule: ReorderRule
) -> dict[str, Any]:
    response = client.post(
        DRAFTS, headers=headers, json={'reorder_rule_ids': [str(rule.id)]}
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return cast(dict[str, Any], response.json())


class TestABoughtProduct:
    def test_a_draft_order_already_made_is_not_ordered_again(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(db_session, po_org, po_template, po_location, po_partner.id)
        post_on_shelf(client, po_auth_headers, po_template, po_location.id, '3')

        first = _drafts(client, po_auth_headers, rule)
        assert Decimal(first['created'][0]['lines'][0]['quantity_ordered']) == 17

        alert = _alert(client, po_auth_headers)
        second = _drafts(client, po_auth_headers, rule)

        # Still short on the shelf, and all of it on order.
        assert alert['available_quantity'] == 3
        assert alert['on_its_way_quantity'] == 17
        assert alert['remaining_to_buy'] == 0
        assert second['created'] == []
        assert [s['reason'] for s in second['skipped']] == ['already_on_order']

    def test_an_order_for_part_of_it_leaves_the_rest_to_buy(
        self,
        client: TestClient,
        db_session: Session,
        po_auth_headers: dict[str, str],
        po_org: Any,
        po_location: Any,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        rule = _rule(db_session, po_org, po_template, po_location, po_partner.id)
        post_on_shelf(client, po_auth_headers, po_template, po_location.id, '3')
        placed = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [
                    {
                        'product_template_id': str(po_template.id),
                        'name': po_template.name,
                        'quantity_ordered': '5',
                    }
                ],
            },
        )
        assert placed.status_code == status.HTTP_201_CREATED, placed.text

        alert = _alert(client, po_auth_headers)
        drafts = _drafts(client, po_auth_headers, rule)

        assert alert['on_its_way_quantity'] == 5
        assert alert['remaining_to_buy'] == 12
        assert Decimal(drafts['created'][0]['lines'][0]['quantity_ordered']) == 12


def _bakery(h: ModuleTestHelper, db: Session) -> tuple[Any, Any, Any, dict[str, str]]:
    """Bread made from flour, with a rule of minimum 10 and maximum 20."""
    org = h.create_org(
        'Bakery',
        ['core', 'items', 'locations', 'warehouse', 'maker', 'purchase_orders'],
    )
    user = h.create_user(org, email=f'b{uuid.uuid4().hex[:6]}@example.com')
    shelf = h.create_storage_location(
        org, h.create_storage_type('Shelf', 'SHELF'), user, name='Shelf'
    )
    flour = h.create_template(org, name='Flour', sku=f'F-{uuid.uuid4().hex[:6]}')
    bread = h.create_template(org, name='Bread R', sku=f'B-{uuid.uuid4().hex[:6]}')
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
    db.commit()
    _rule(db, org, bread, shelf)
    return org, bread, shelf, h.get_auth_headers(user)


def _plan(
    client: TestClient, headers: dict[str, str], bread: Any, shelf: Any, qty: str
) -> None:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(bread.id),
            'planned_qty': qty,
            'output_location_id': str(shelf.id),
            'production_date': date.today().isoformat(),
            'confirm_shortage': True,
        },
    )
    assert created.status_code == 201, created.text


def _to_make(client: TestClient, headers: dict[str, str]) -> list[Decimal]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': _later(), 'limit': 50},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return [
        Decimal(str(i['count']))
        for i in response.json()['work_items']['items']
        if i['source_kind'] == 'production_proposal'
    ]


class TestAMadeProduct:
    def test_a_planned_run_is_not_proposed_again(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        _org, bread, shelf, headers = _bakery(h, db_session)
        _plan(client, headers, bread, shelf, '5')

        alert = _alert(client, headers)

        # Nothing on the shelf, maximum 20, five already planned: fifteen.
        assert alert['make_instead'] is True
        assert alert['on_its_way_quantity'] == 5
        assert alert['remaining_to_buy'] == 15
        assert _to_make(client, headers) == [Decimal('15')]

    def test_with_nothing_planned_the_whole_shortage_is_proposed(
        self, client: TestClient, h: ModuleTestHelper, db_session: Session
    ) -> None:
        _org, _bread, _shelf, headers = _bakery(h, db_session)

        alert = _alert(client, headers)

        assert alert['on_its_way_quantity'] == 0
        assert alert['remaining_to_buy'] == 20
        assert _to_make(client, headers) == [Decimal('20')]
