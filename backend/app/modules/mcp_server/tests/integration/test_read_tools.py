"""The seven read tools and two resources, and the tenant/permission line they hold."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.mcp_server.tests.conftest import issue_key
from tests.integration._shelf import anchor_pending_records


def _tool(client: TestClient, key: str, name: str, arguments: dict):
    response = client.post(
        '/api/v1/mcp-server/mcp',
        json={
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {
                'name': name,
                'arguments': arguments,
                '_meta': {
                    'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                    'io.modelcontextprotocol/clientCapabilities': {},
                },
            },
        },
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
            'Mcp-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'tools/call',
            'Mcp-Name': name,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['result']


def _structured(result: dict) -> dict:
    assert result.get('isError') is not True, result
    return result['structuredContent']


class TestSearchAndRead:
    def test_search_items_finds_stock(
        self, client: TestClient, mcp_key: str, item: Item
    ) -> None:
        result = _tool(client, mcp_key, 'search_items', {'query': 'Olive'})

        rows = _structured(result)['stock']
        assert [row['name'] for row in rows] == ['Olive Oil']
        assert Decimal(str(rows[0]['offered_quantity'])) == Decimal('5')
        assert rows[0]['id'] == str(item.id)
        assert rows[0]['shelf_name'] == 'Cold Storage A'

    def test_search_items_finds_a_barcode(
        self,
        client: TestClient,
        db_session,
        mcp_org: Organization,
        shelf,
        mcp_key: str,
    ) -> None:
        from app.models.item import Item as ItemModel

        record = ItemModel(
            organization_id=mcp_org.id,
            storage_location_id=shelf.id,
            name='Uncatalogued Thing',
            barcode='5901234567890',
            quantity=Decimal('2'),
        )
        db_session.add(record)
        from tests.integration._shelf import anchor_pending_records

        anchor_pending_records(db_session)
        db_session.commit()

        result = _tool(client, mcp_key, 'search_items', {'query': '5901234567890'})

        records = _structured(result)['records']
        assert [row['id'] for row in records] == [str(record.id)]

    def test_get_item_answers_with_its_batch(
        self, client: TestClient, mcp_key: str, item: Item, lot: StockLot
    ) -> None:
        result = _tool(client, mcp_key, 'get_item', {'item_id': str(item.id)})

        payload = _structured(result)
        assert payload['item']['name'] == 'Olive Oil'
        assert payload['item']['lot_id'] == str(lot.id)
        assert payload['lot']['name'] == 'LOT-OLIVE-1'

    def test_get_item_refuses_an_unknown_record(
        self, client: TestClient, mcp_key: str
    ) -> None:
        result = _tool(
            client,
            mcp_key,
            'get_item',
            {'item_id': '00000000-0000-0000-0000-000000000001'},
        )

        assert result['isError'] is True
        assert 'ITEM_NOT_FOUND' in result['content'][0]['text']


class TestLocations:
    def test_list_locations_answers_the_shelf(
        self, client: TestClient, mcp_key: str, shelf
    ) -> None:
        result = _tool(client, mcp_key, 'list_locations', {})

        locations = _structured(result)['locations']
        assert [location['id'] for location in locations] == [str(shelf.id)]
        assert locations[0]['parent_id'] is None

    def test_get_location_tree_answers_roots(
        self, client: TestClient, mcp_key: str, shelf
    ) -> None:
        result = _tool(client, mcp_key, 'get_location_tree', {})

        roots = _structured(result)['roots']
        assert [root['id'] for root in roots] == [str(shelf.id)]

    def test_the_whole_tree_is_read_past_one_core_page(
        self,
        client: TestClient,
        mcp_key: str,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
    ) -> None:
        """The tree is every location, not the first page of them.

        The CoreAPI listing is capped per request; the whole-tree read used one
        request and answered a smaller tree with nothing saying so.
        """
        zone = StorageLocation(
            organization_id=mcp_org.id, created_by=mcp_user.id, name='Zone'
        )
        db_session.add(zone)
        db_session.flush()
        db_session.add_all(
            [
                StorageLocation(
                    organization_id=mcp_org.id,
                    created_by=mcp_user.id,
                    name=f'Shelf {index:03d}',
                    parent_id=zone.id,
                )
                for index in range(501)
            ]
        )
        db_session.commit()

        result = _tool(client, mcp_key, 'get_location_tree', {})

        roots = _structured(result)['roots']
        assert len(roots) == 1
        assert len(roots[0]['children']) == 501

    def test_get_location_tree_refuses_an_unknown_id(
        self, client: TestClient, mcp_key: str
    ) -> None:
        result = _tool(
            client,
            mcp_key,
            'get_location_tree',
            {'root_id': '00000000-0000-0000-0000-000000000002'},
        )

        assert result['isError'] is True
        assert 'LOCATION_NOT_FOUND' in result['content'][0]['text']


class TestStockAndLots:
    def test_get_stock_levels_answers_shelf_totals(
        self, client: TestClient, mcp_key: str, shelf, item: Item
    ) -> None:
        result = _tool(client, mcp_key, 'get_stock_levels', {'shelf_id': str(shelf.id)})

        totals = _structured(result)['shelf_totals']
        assert len(totals) == 1
        assert Decimal(str(totals[0]['quantity'])) == Decimal('5')

    def test_get_stock_levels_answers_quant_rows(
        self, client: TestClient, mcp_key: str, item: Item
    ) -> None:
        result = _tool(
            client,
            mcp_key,
            'get_stock_levels',
            {'product_template_id': str(item.template_id)},
        )

        rows = _structured(result)['rows']
        assert len(rows) == 1
        assert Decimal(str(rows[0]['available_quantity'])) == Decimal('5')

    def test_list_lots_answers_the_batches(
        self, client: TestClient, mcp_key: str, lot: StockLot
    ) -> None:
        result = _tool(client, mcp_key, 'list_lots', {})

        payload = _structured(result)
        assert [batch['name'] for batch in payload['items']] == ['LOT-OLIVE-1']
        assert payload['total'] == 1

    def test_get_lot_detail_counts_what_stands_on_shelves(
        self, client: TestClient, mcp_key: str, lot: StockLot, item: Item
    ) -> None:
        result = _tool(client, mcp_key, 'list_lots', {'lot_id': str(lot.id)})

        detail = _structured(result)['detail']
        assert detail['name'] == 'LOT-OLIVE-1'
        assert Decimal(str(detail['on_hand'])) == Decimal('5')

    def test_get_expiring_soon_answers_the_window_and_forecast(
        self, client: TestClient, mcp_key: str, item: Item
    ) -> None:
        result = _tool(client, mcp_key, 'get_expiring_soon', {'days': 7})

        payload = _structured(result)
        assert [row['item_id'] for row in payload['items']] == [str(item.id)]
        assert payload['forecast']
        assert payload['shelf_count'] is None

    def test_get_expiring_soon_counts_a_named_shelf(
        self, client: TestClient, mcp_key: str, item: Item, shelf
    ) -> None:
        result = _tool(
            client,
            mcp_key,
            'get_expiring_soon',
            {'days': 7, 'shelf_id': str(shelf.id)},
        )

        payload = _structured(result)
        assert payload['shelf_count'] == 1

    def test_a_cut_answer_says_how_many_it_cut(
        self,
        client: TestClient,
        mcp_key: str,
        db_session: Session,
        mcp_org: Organization,
        shelf,
        item: Item,
    ) -> None:
        """The answer names the total and that limit cut it, not only the page.

        It used to read the whole quant list and slice it silently: a caller
        with 200 rows and limit 1 had no way to know 199 were missing.
        """
        from app.models.product_template import ProductTemplate

        other = ProductTemplate(organization_id=mcp_org.id, name='Other Product')
        db_session.add(other)
        db_session.flush()
        second = Item(
            organization_id=mcp_org.id,
            storage_location_id=shelf.id,
            template_id=other.id,
            name='Other Product',
            quantity=Decimal('2'),
        )
        db_session.add(second)
        anchor_pending_records(db_session)
        db_session.commit()

        result = _tool(client, mcp_key, 'get_stock_levels', {'limit': 1})

        payload = _structured(result)
        assert len(payload['rows']) == 1
        assert payload['total'] == 2
        assert payload['has_more'] is True

    def test_a_whole_answer_is_not_marked_as_cut(
        self, client: TestClient, mcp_key: str, item: Item
    ) -> None:
        result = _tool(client, mcp_key, 'get_stock_levels', {'limit': 10})

        payload = _structured(result)
        assert len(payload['rows']) == 1
        assert payload['total'] == 1
        assert payload['has_more'] is False

    def test_an_opened_package_is_judged_by_its_use_by_date(
        self,
        client: TestClient,
        mcp_key: str,
        db_session: Session,
        mcp_org: Organization,
        shelf,
    ) -> None:
        """A use-by inside the window is in the window, whatever the batch says.

        The query filters on the effective expiry (the earlier of the batch
        date and the use-by), but the answer filtered again on the raw batch
        date: an opened jar with a use-by in three days was missing from
        items while the forecast and GET /items/expiring counted it.
        """
        use_by = date.today() + timedelta(days=3)
        opened = Item(
            organization_id=mcp_org.id,
            storage_location_id=shelf.id,
            name='Open jam',
            quantity=Decimal('1'),
            expiry_date=date.today() + timedelta(days=220),
            meta_data={'opened': {'use_by': use_by.isoformat()}},
        )
        db_session.add(opened)
        anchor_pending_records(db_session)
        db_session.commit()

        result = _tool(client, mcp_key, 'get_expiring_soon', {'days': 7})

        payload = _structured(result)
        row = next(row for row in payload['items'] if row['item_id'] == str(opened.id))
        assert row['expiry_date'] == use_by.isoformat()
        assert row['days_left'] == 3

    def test_the_window_is_not_cut_from_the_expired_rows(
        self,
        client: TestClient,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        shelf: StorageLocation,
        item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The cap counts the window, not the oldest rows before it.

        With the cap forced to one row, the single row read must be the one in
        the window. Reading the FEFO list and filtering afterwards read the
        expired row instead and answered an empty window.
        """
        from app.modules.mcp_server.tools import _stock

        expired = Item(
            organization_id=mcp_org.id,
            storage_location_id=shelf.id,
            name='Expired olive oil',
            quantity=Decimal('1'),
            expiry_date=date.today() - timedelta(days=30),
        )
        db_session.add(expired)
        anchor_pending_records(db_session)
        db_session.flush()
        db_session.commit()
        # The stale row sorts before the live one.
        raw = issue_key(db_session, mcp_org, mcp_user)
        monkeypatch.setattr(_stock, '_EXPIRY_LOOKUP_CAP', 1)

        result = _tool(client, raw, 'get_expiring_soon', {'days': 7})

        payload = _structured(result)
        assert [row['item_id'] for row in payload['items']] == [str(item.id)]


class TestPermissions:
    def test_a_key_without_items_read_can_read_locations_but_not_stock(
        self,
        client: TestClient,
        db_session,
        mcp_org: Organization,
        mcp_user: User,
        shelf,
    ) -> None:
        key = issue_key(
            db_session,
            mcp_org,
            mcp_user,
            permissions=['mcp_server:use', 'locations:read'],
        )

        locations = _tool(client, key, 'list_locations', {})
        stock = _tool(client, key, 'search_items', {'query': 'Olive'})

        assert _structured(locations)['locations']
        assert stock['isError'] is True
        assert 'PERMISSION_REQUIRED' in stock['content'][0]['text']

    def test_a_key_without_locations_read_can_read_stock_but_not_locations(
        self,
        client: TestClient,
        db_session,
        mcp_org: Organization,
        mcp_user: User,
        item: Item,
    ) -> None:
        key = issue_key(
            db_session,
            mcp_org,
            mcp_user,
            permissions=['mcp_server:use', 'items:read'],
        )

        stock = _tool(client, key, 'search_items', {'query': 'Olive'})
        locations = _tool(client, key, 'list_locations', {})

        assert _structured(stock)['stock']
        assert locations['isError'] is True
        assert 'PERMISSION_REQUIRED' in locations['content'][0]['text']


class TestTenantIsolation:
    def test_search_never_crosses_the_organization(
        self, client: TestClient, mcp_key_b: str, item: Item
    ) -> None:
        result = _tool(client, mcp_key_b, 'search_items', {'query': 'Olive'})

        payload = _structured(result)
        assert payload['stock'] == []
        assert payload['records'] == []

    def test_one_records_id_does_not_open_another_organization(
        self, client: TestClient, mcp_key_b: str, item: Item
    ) -> None:
        result = _tool(client, mcp_key_b, 'get_item', {'item_id': str(item.id)})

        assert result['isError'] is True
        assert 'ITEM_NOT_FOUND' in result['content'][0]['text']

    def test_a_batch_id_does_not_cross_either(
        self, client: TestClient, mcp_key_b: str, lot: StockLot
    ) -> None:
        result = _tool(client, mcp_key_b, 'list_lots', {'lot_id': str(lot.id)})

        assert result['isError'] is True
        assert 'LOT_NOT_FOUND' in result['content'][0]['text']


class TestResources:
    def test_the_overview_counts_only_this_workspace(
        self, client: TestClient, mcp_key: str, item: Item, item_b: Item
    ) -> None:
        response = client.post(
            '/api/v1/mcp-server/mcp',
            json={
                'jsonrpc': '2.0',
                'id': 4,
                'method': 'resources/read',
                'params': {
                    'uri': 'inventari://org/overview',
                    '_meta': {
                        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                        'io.modelcontextprotocol/clientCapabilities': {},
                    },
                },
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {mcp_key}',
                'Mcp-Protocol-Version': '2026-07-28',
                'Mcp-Method': 'resources/read',
                'Mcp-Name': 'inventari://org/overview',
            },
        )
        assert response.status_code == 200, response.text
        contents = response.json()['result']['contents']
        overview = json.loads(contents[0]['text'])
        # Org B holds one record too; a count of two would cross the boundary.
        assert overview['total_items'] == 1

    def test_the_location_tree_is_the_workspace_tree(
        self, client: TestClient, mcp_key: str, shelf
    ) -> None:
        response = client.post(
            '/api/v1/mcp-server/mcp',
            json={
                'jsonrpc': '2.0',
                'id': 5,
                'method': 'resources/read',
                'params': {
                    'uri': 'inventari://locations/tree',
                    '_meta': {
                        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                        'io.modelcontextprotocol/clientCapabilities': {},
                    },
                },
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {mcp_key}',
                'Mcp-Protocol-Version': '2026-07-28',
                'Mcp-Method': 'resources/read',
                'Mcp-Name': 'inventari://locations/tree',
            },
        )
        assert response.status_code == 200, response.text
        payload = json.loads(response.json()['result']['contents'][0]['text'])
        assert [root['id'] for root in payload['roots']] == [str(shelf.id)]
