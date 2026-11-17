"""A demo visitor connects an AI agent to their own sandbox, and only to it.

The public demo publishes no key. Every visitor is the administrator of an
organization of their own (``docs/DEMO.md``), so the key an agent uses is one
the visitor issues there: it reads and writes that copy and nothing else, and
the nightly rebuild drops it with the rest of the sandbox. For that to work on
the first click, a sandbox the pool hands out has to have the API Keys and MCP
Server modules on, its administrator has to be allowed to issue a key for the
endpoint, and the endpoint has to answer on the address the demo is published
at, which the seed saves as the sandbox's allowed host.

Each sandbox here is the one ``demo fill-pool`` makes (``two_sandboxes``), and
every key is issued through the API Keys endpoint the issuing dialog calls.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.modules.api_keys.models import ApiKey
from app.services.token_service import create_access_token
from tests.integration._demo_world import DEMO_ADDRESS

pytestmark = pytest.mark.integration

_DEMO_HOST = DEMO_ADDRESS.removeprefix('https://')

_READ = ['mcp_server:use', 'items:read', 'locations:read']
_WRITE = ['mcp_server:use', 'items:read', 'items:write']

_PROTOCOL = '2026-07-28'
_META = {
    'io.modelcontextprotocol/protocolVersion': _PROTOCOL,
    'io.modelcontextprotocol/clientCapabilities': {},
}


def _as(user_id: uuid.UUID) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


def _issue(
    client: TestClient, admin_id: uuid.UUID, permissions: list[str]
) -> dict[str, Any]:
    """Issue a key the way the API Keys dialog does, as the sandbox's visitor."""
    response = client.post(
        '/api/v1/api-keys',
        json={'name': 'My agent', 'permissions': permissions},
        headers=_as(admin_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _call(
    client: TestClient,
    key: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    host: str = _DEMO_HOST,
):
    return client.post(
        '/api/v1/mcp-server/mcp',
        json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'tools/call',
            'params': {'name': tool, 'arguments': arguments, '_meta': dict(_META)},
        },
        headers={
            'Content-Type': 'application/json',
            'X-API-Key': key,
            'Host': host,
            'Mcp-Protocol-Version': _PROTOCOL,
            'Mcp-Method': 'tools/call',
            'Mcp-Name': tool,
        },
    )


def _result(response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    return response.json()['result']


def _a_record_on_hand(db: Session, org_id: uuid.UUID) -> Item:
    record = db.scalar(
        select(Item)
        .where(
            Item.organization_id == org_id,
            Item.template_id.is_not(None),
            Item.quantity > 0,
            Item.is_deleted.is_(False),
        )
        .order_by(Item.name, Item.id)
        .limit(1)
    )
    assert record is not None, 'the sandbox has no stock on hand'
    return record


class TestASandboxIsReadyForAnAgent:
    def test_the_modules_are_on_and_no_key_is_published(
        self, db_session: Session, two_sandboxes
    ) -> None:
        for org_id, _admin_id in two_sandboxes:
            org = db_session.get(Organization, org_id)
            assert org is not None
            assert {'api_keys', 'mcp_server'} <= set(org.enabled_modules or []), (
                'a visitor would have to find Apps and switch two modules on '
                'before the API Keys screen exists'
            )
            keys = db_session.scalar(
                select(func.count())
                .select_from(ApiKey)
                .where(ApiKey.organization_id == org_id)
            )
            assert keys == 0, 'a sandbox is handed out with a key already in it'

    def test_the_visitor_issues_a_read_key_and_a_write_key(
        self, client: TestClient, two_sandboxes
    ) -> None:
        _org_id, admin_id = two_sandboxes[0]

        read = _issue(client, admin_id, _READ)
        write = _issue(client, admin_id, _WRITE)

        assert set(read['permissions']) == set(_READ)
        assert set(write['permissions']) == set(_WRITE)


class TestAKeyStaysInItsSandbox:
    def test_reads_and_writes_reach_only_the_issuing_sandbox(
        self, client: TestClient, db_session: Session, two_sandboxes
    ) -> None:
        """One test over every door: each sandbox costs a seed to open."""
        (mine, me), (theirs, _them) = two_sandboxes
        key = _issue(client, me, _WRITE)['raw_key']
        own = _a_record_on_hand(db_session, mine)
        foreign = _a_record_on_hand(db_session, theirs)
        foreign_quantity = foreign.quantity
        assert own.name == foreign.name, 'the two sandboxes share one seed'

        found = _result(_call(client, key, 'search_items', {'query': own.name}))
        seen = {
            row['id']
            for row in [
                *found['structuredContent']['stock'],
                *found['structuredContent']['records'],
            ]
        }
        assert str(own.id) in seen
        their_ids = set(
            map(
                str,
                db_session.scalars(
                    select(Item.id).where(Item.organization_id == theirs)
                ),
            )
        )
        assert not seen & their_ids, "the agent found the other sandbox's stock"

        opened = _result(_call(client, key, 'get_item', {'item_id': str(foreign.id)}))
        assert opened['isError'] is True
        assert 'ITEM_NOT_FOUND' in opened['content'][0]['text']

        refused = _result(
            _call(
                client,
                key,
                'correct_stock',
                {'item_id': str(foreign.id), 'quantity': 0, 'reason': 'Spoil it'},
            )
        )
        assert refused['isError'] is True
        db_session.expire_all()
        assert db_session.get(Item, foreign.id).quantity == foreign_quantity

        counted = Decimal(str(own.quantity)) - 1
        corrected = _result(
            _call(
                client,
                key,
                'correct_stock',
                {
                    'item_id': str(own.id),
                    'quantity': str(counted),
                    'reason': 'One broke on the shelf',
                },
            )
        )
        assert corrected.get('isError') is not True, corrected
        db_session.expire_all()
        assert Decimal(str(db_session.get(Item, own.id).quantity)) == counted

    def test_the_endpoint_refuses_a_host_other_than_the_demo_address(
        self, client: TestClient, two_sandboxes
    ) -> None:
        _org_id, admin_id = two_sandboxes[0]
        key = _issue(client, admin_id, _READ)['raw_key']

        response = _call(
            client, key, 'list_locations', {}, host='rebinding.example.net'
        )

        assert response.status_code == 421
