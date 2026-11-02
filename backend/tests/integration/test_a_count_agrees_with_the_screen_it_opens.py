"""Every number that leads somewhere, against the screen it leads to.

A person who taps a count and lands on a different number concludes the app
is wrong. The demo a visitor receives said "3 low stock" on the launcher, "14
need attention" on the overview and 17 records on the list that overview
opens, each correct by its own definition and none saying what it counted.

Each test here is one pair on an organization seeded the way the demo pool
seeds one: what the count reads, and what its destination reports. Where the
two are in different units the destination has to report the count's unit as
well, which is what ``product_count`` beside a list of records is for.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date
from typing import Any

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.services.items.low_stock import low_stock_template_ids
from app.services.token_service import create_access_token
from tests.integration._demo_world import ids, pooled_sandboxes

pytestmark = pytest.mark.integration


@pytest.fixture
def sandbox(demo_world, async_engine_fixture) -> tuple[uuid.UUID, uuid.UUID]:
    payload = demo_world('pooled-sandboxes', pooled_sandboxes(async_engine_fixture))
    return ids(payload[0])


@pytest.fixture
def read(sandbox, db_session: Session, client):
    """GET as the sandbox's administrator, handed over the way a visitor gets it."""
    _org_id, user_id = sandbox
    admin = db_session.get(User, user_id)
    assert admin is not None
    admin.is_active = True
    db_session.commit()
    headers = {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }

    def get(path: str, **params: Any) -> Any:
        response = client.get(f'/api/v1{path}', headers=headers, params=params)
        assert response.status_code == 200, f'{path}: {response.text}'
        return response.json()

    return get


def _keep_a_short_product_in_two_records(db: Session, org_id: uuid.UUID) -> None:
    """What the demo's full seed does by chance and the suite's smaller one may not.

    One short product held as two records is where a count of products and a
    list of records part: the second record stays under the threshold, which
    moves up with it.
    """
    template_id = db.scalars(low_stock_template_ids(org_id)).first()
    assert template_id is not None, 'the seed has to leave a product short'
    record = db.scalars(
        select(Item).where(
            Item.organization_id == org_id,
            Item.template_id == template_id,
            Item.is_deleted.is_(False),
            Item.quantity > 0,
        )
    ).first()
    assert record is not None
    copied = {
        attr.key: getattr(record, attr.key) for attr in inspect(Item).column_attrs
    }
    copied.update(id=uuid.uuid4(), quantity=1, label_code=None)
    db.add(Item(**copied))
    template = db.get(ProductTemplate, template_id)
    assert template is not None
    template.min_quantity = (template.min_quantity or 0) + 1
    db.commit()


def _list_total(read, **filters: Any) -> int:
    return read('/items', limit=1, **filters)['total']


@pytest.mark.parametrize('hide_module_data', [False, True])
class TestTheInventoryPath:
    """The launcher badge, the overview card and the statistics tile: one number."""

    def test_needs_attention_is_the_rows_its_link_opens(
        self, read, sandbox, db_session: Session, hide_module_data: bool
    ) -> None:
        _keep_a_short_product_in_two_records(db_session, sandbox[0])
        scope = {'exclude_module_contexts': hide_module_data}
        counts = read('/items/attention-counts', **scope)
        assert counts['records'] > 0, 'the seed has to give the card something to say'
        assert counts['records'] == _list_total(read, needs_attention=True, **scope)

    def test_running_low_is_the_products_its_list_names(
        self, read, sandbox, db_session: Session, hide_module_data: bool
    ) -> None:
        _keep_a_short_product_in_two_records(db_session, sandbox[0])
        scope = {'exclude_module_contexts': hide_module_data}
        short = read('/items/attention-counts', **scope)['low_stock']
        assert short > 0
        listed = read('/items/aggregates', only_low_stock=True, **scope)
        assert listed['product_count'] == short
        assert listed['count'] > short

    def test_dated_tiles_are_the_rows_they_open(
        self, read, hide_module_data: bool
    ) -> None:
        scope = {'exclude_module_contexts': hide_module_data}
        counts = read('/items/attention-counts', **scope)
        assert counts['expired'] == _list_total(read, only_expired=True, **scope)
        assert counts['expiring_soon'] == _list_total(read, expiring_days=7, **scope)


def test_the_records_tile_is_the_list_it_opens(read) -> None:
    settings = read('/organizations/my').get('settings') or {}
    scope = {'exclude_module_contexts': settings.get('show_module_data') is not True}
    assert read('/stats/overview')['total_items'] == _list_total(read, **scope)


def test_a_category_card_counts_the_products_its_list_shows(read) -> None:
    categories = read('/categories', with_counts=True, limit=200)
    rows = categories if isinstance(categories, list) else categories['items']
    counted = [row for row in rows if row.get('items_count')]
    assert counted
    for category in counted:
        listed = read('/items/aggregates', category_id=category['id'])
        assert listed['product_count'] == category['items_count'], category['name']


class TestTheEquipmentPath:
    def test_the_tile_counts_the_warranty_alerts_the_overview_shows(self, read) -> None:
        overview = read('/equipment/dashboard')['warranty_alerts']
        assert overview
        assert read('/equipment/warranty-alerts')['total'] == len(overview)

    def test_the_summary_counts_the_lists_it_stands_for(self, read) -> None:
        dashboard = read('/equipment/dashboard')
        fleet = dashboard['total_assets'] - dashboard['retired']
        assert fleet == read('/equipment/assets', limit=1)['total']
        assert (
            dashboard['active_assignments']
            == read('/equipment/assets', limit=1, checked_out=True)['total']
        )

    def test_a_category_row_counts_the_list_it_opens(self, read) -> None:
        assets = read('/equipment/assets', limit=200)['items']
        rows = Counter(asset['category_id'] for asset in assets)
        assert rows
        for category_id, count in rows.items():
            assert (
                read('/equipment/assets', limit=1, category_id=category_id)['total']
                == count
            )


def test_the_warehouse_badge_is_what_the_to_do_page_reports(read) -> None:
    today = date.today().isoformat()
    queue = read('/warehouse/todo', date_to=today, limit=50, work_limit=50)
    badge = read('/warehouse/todo', date_to=today, limit=1)
    assert queue['work_items']['total'] > 0
    assert (
        badge['work_items']['total'] + badge['decisions']['quarantine']['total']
        == queue['work_items']['total'] + queue['decisions']['quarantine']['total']
    )


def test_the_approvals_row_is_the_queue_it_opens(read) -> None:
    open_states = 'PENDING,IN_PROGRESS'
    waiting = read('/approvals/requests', status=open_states, limit=1)['total']
    assert waiting > 0
    rows = read('/approvals/requests', status=open_states, limit=50)['items']
    assert len(rows) == waiting


def test_a_recipe_card_says_what_its_detail_says(read) -> None:
    listed = read('/recipes', limit=50)
    rows = listed if isinstance(listed, list) else listed['items']
    assert rows
    for recipe in rows:
        detail = read(f'/recipes/{recipe["id"]}/availability')
        assert detail['match_percentage'] == pytest.approx(
            recipe['ingredients_available'] / recipe['ingredients_total'], abs=0.01
        ), recipe['name']
