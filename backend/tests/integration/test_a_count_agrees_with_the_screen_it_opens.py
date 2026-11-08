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
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.open_package import OPENED_KEY
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.services.items.low_stock import claimed_tags_for, low_stock_template_ids
from app.services.token_service import create_access_token
from tests.integration._demo_world import ids, pooled_sandboxes

pytestmark = pytest.mark.integration


@pytest.fixture
def sandbox(demo_world, async_engine_fixture) -> tuple[uuid.UUID, uuid.UUID]:
    payload = demo_world('pooled-sandboxes', pooled_sandboxes(async_engine_fixture))
    return ids(payload[0])


@pytest.fixture
def headers(sandbox, db_session: Session) -> dict[str, str]:
    """The sandbox's administrator, handed over the way a visitor gets it."""
    _org_id, user_id = sandbox
    admin = db_session.get(User, user_id)
    assert admin is not None
    admin.is_active = True
    db_session.commit()
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


@pytest.fixture
def read(headers, client):
    """GET as the sandbox's administrator."""

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

    The seed dates its records at random, and a dated record of a short
    product parts the two the other way: the shares count it once as dated
    and again in its product, which cancelled the added record on some runs.
    The short products' records carry no date here, so the shares summed fall
    short of the list on every run, not on most.
    """
    short = list(db.scalars(low_stock_template_ids(org_id)))
    # Short whichever way the organization sets its lists, so both settings
    # of the module data see the added record.
    visible = list(db.scalars(low_stock_template_ids(org_id, claimed_tags_for(True))))
    assert visible, 'the seed has to leave a product short'
    for dated in db.scalars(
        select(Item).where(Item.organization_id == org_id, Item.template_id.in_(short))
    ):
        dated.expiry_date = None
        meta = dated.meta_data or {}
        if OPENED_KEY in meta:
            dated.meta_data = {key: meta[key] for key in meta if key != OPENED_KEY}
    record = db.scalars(
        select(Item).where(
            Item.organization_id == org_id,
            Item.template_id == visible[0],
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
    template = db.get(ProductTemplate, visible[0])
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
        listed = _list_total(read, needs_attention=True, **scope)
        shares = counts['expired'] + counts['expiring_soon'] + counts['low_stock']
        assert shares < listed, 'the seed has to part the shares from the rows'
        assert counts['records'] == listed

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


def _flatten(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        each for node in nodes for each in (node, *_flatten(node.get('children') or []))
    ]


@pytest.mark.parametrize('hide_module_data', [False, True])
def test_a_place_counts_the_records_its_products_tab_lists(
    read, hide_module_data: bool
) -> None:
    """The tree, the place cards and the overview's places, against the place.

    Each of them prints ``subtree_items_count`` and opens the place, whose
    Products tab lists the records standing on it and, with "Include
    locations inside" ticked, the records of every place below it as well.
    """
    tree = read(
        '/locations/tree', exclude_module_contexts=hide_module_data, counts=True
    )
    counted = [node for node in _flatten(tree) if node['subtree_items_count']]
    assert counted
    for node in counted:
        path = f'/locations/{node["id"]}/items'
        assert read(path, limit=1)['total'] == node['items_count'], node['name']
        assert (
            read(path, limit=1, include_inside=True)['total']
            == node['subtree_items_count']
        ), node['name']


def test_an_equipment_location_row_counts_the_assets_its_link_opens(read) -> None:
    """Read with the scope the module's own locations screen asks for."""
    rows = read('/locations', module_scope='equipment', counts=True, limit=200)
    here = [row for row in rows['items'] if row['items_count']]
    assert here
    for row in here:
        listed = read('/equipment/assets', limit=1, location_id=row['id'])['total']
        assert listed == row['items_count'], row['name']


def test_a_production_month_counts_the_runs_its_list_shows_closed_in_it(
    read,
) -> None:
    tz = ZoneInfo(read('/organizations/my').get('timezone') or 'UTC')
    months = read('/maker/production/monthly-result', months=6)
    assert any(month['orders'] for month in months), 'the seed has to close a run'
    runs = read('/maker/production/orders', status='COMPLETED', limit=200)
    assert runs['total'] == len(runs['items'])
    closed = Counter(
        datetime.fromisoformat(run['completed_at']).astimezone(tz).strftime('%Y-%m')
        for run in runs['items']
    )
    for month in months:
        assert month['orders'] == closed[month['month']], month['month']


def test_a_shopping_list_card_counts_the_lines_its_page_lists(read) -> None:
    """The card, the overview's line and the page read one list.

    The overview shows the first active list; the card and the page group
    that list's lines into bought and still to buy.
    """
    active = read('/shopping-lists', active_only=True, limit=50)['items']
    assert active, 'the seed has to leave a list to shop from'
    lines = read(f'/shopping-lists/{active[0]["id"]}')['items']
    assert lines
    bought = [line for line in lines if line['is_purchased']]
    to_buy = [line for line in lines if not line['is_purchased']]
    assert len(bought) + len(to_buy) == len(lines)


def test_a_recipe_tag_chip_counts_the_recipes_it_narrows_to(read) -> None:
    tags = read('/recipes/tags', limit=200)['items']
    assert tags
    for tag in tags:
        narrowed = read('/recipes', tags=tag['name'], limit=1)['total']
        assert narrowed == tag['count'], tag['name']


def test_the_cook_chips_count_recipes_whose_page_says_the_same(
    read, headers, client
) -> None:
    """The chips "Ready to cook" and "Nearly there", against each recipe's page.

    The two chips split one answer of the availability list at a full match;
    a recipe they place has to read the same on the page it opens. The
    suite's seed leaves nothing ready, so one recipe is written from a record
    on the shelf and the first chip has a recipe to count.
    """
    record = next(
        item
        for item in read('/items', limit=50)['items']
        if item['template_id'] and item['uom_id'] and float(item['quantity']) >= 2
    )
    written = client.post(
        '/api/v1/recipes',
        headers=headers,
        json={
            'name': 'From the shelf',
            'ingredients': [
                {
                    'name': record['name'],
                    'template_id': record['template_id'],
                    'uom_id': record['uom_id'],
                    'quantity': '1',
                }
            ],
        },
    )
    assert written.status_code == 201, written.text
    near = read('/recipes/available', min_match=0.5, limit=200)['items']
    ready = [recipe for recipe in near if recipe['match_percentage'] >= 1]
    assert ready
    assert len(ready) < len(near), 'the seed has to leave a recipe nearly there'
    assert len(ready) == read('/recipes/available', limit=1)['total']
    for recipe in near:
        page = read(f'/recipes/{recipe["id"]}/availability')['match_percentage']
        assert page == pytest.approx(recipe['match_percentage']), recipe['name']


def test_the_stock_takes_row_counts_the_takes_its_link_lists(
    read, headers, client
) -> None:
    """The seed's one take is finished; a take started on it gives the row a count."""
    place = next(
        node
        for node in _flatten(read('/locations/tree', counts=True))
        if node['items_count']
    )
    started = client.post(
        '/api/v1/stock-takes',
        headers=headers,
        json={'name': 'Spot count', 'location_id': place['id']},
    )
    assert started.status_code == 201, started.text
    row = read('/stock-takes', status_filter='in_progress', limit=5)['total']
    assert row > 0
    listed = read('/stock-takes', status_filter='in_progress', limit=50)['items']
    every = read('/stock-takes', limit=50)['items']
    assert row == len(listed)
    assert row == sum(take['status'] == 'in_progress' for take in every)
