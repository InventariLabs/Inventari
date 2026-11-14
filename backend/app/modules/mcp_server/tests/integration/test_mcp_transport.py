"""The mounted MCP endpoint: the 2026-07-28 revision, authentication, and the door.

A 2026-07-28 request is one self-contained POST: no initialize handshake and no
session id. The required `params._meta` envelope and the `Mcp-Protocol-Version`
/ `Mcp-Method` routing headers are part of the wire, so these tests send the
same shape a client does rather than a bare JSON-RPC body.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit_actor import current_actor
from app.models.organization import Organization
from app.models.user import User
from app.modules.api_keys.models import ApiKey

_PATH = '/api/v1/mcp-server/mcp'
_PROTOCOL = '2026-07-28'
_META = {
    'io.modelcontextprotocol/protocolVersion': _PROTOCOL,
    'io.modelcontextprotocol/clientCapabilities': {},
}


def rpc(
    client: TestClient,
    key: str | None,
    method: str,
    *,
    params: dict | None = None,
    name: str | None = None,
    host: str | None = None,
    origin: str | None = None,
    protocol: str = _PROTOCOL,
    own_header: bool = False,
):
    headers = {
        'Content-Type': 'application/json',
        'Mcp-Protocol-Version': protocol,
        'Mcp-Method': method,
    }
    if key is not None:
        if own_header:
            headers['X-API-Key'] = key
        else:
            headers['Authorization'] = f'Bearer {key}'
    if name is not None:
        headers['Mcp-Name'] = name
    if host is not None:
        headers['Host'] = host
    if origin is not None:
        headers['Origin'] = origin
    body = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': method,
        'params': {**(params or {}), '_meta': _META},
    }
    return client.post(_PATH, json=body, headers=headers)


def _revoke(db: Session, raw_key: str) -> None:
    db.execute(
        update(ApiKey)
        .where(ApiKey.hashed_key == hashlib.sha256(raw_key.encode()).hexdigest())
        .values(is_active=False)
    )
    db.commit()


class TestAuthentication:
    def test_no_key_is_refused_with_the_bearer_challenge(
        self, client: TestClient
    ) -> None:
        response = rpc(client, None, 'tools/list')

        assert response.status_code == 401
        assert response.headers['www-authenticate'].startswith('Bearer')
        assert response.json()['detail']['code'] == 'MCP_AUTH_REQUIRED'
        # The key has its own header, and Core marks the Bearer form
        # Deprecation; the refusal has to name the header the client should
        # send, not one whose answer tells its maintainer to switch.
        assert 'X-API-Key' in response.json()['detail']['message']

    def test_an_unknown_key_is_refused(self, client: TestClient) -> None:
        response = rpc(client, 'inv_live_nosuchkey00000000', 'tools/list')

        assert response.status_code == 401
        assert response.headers['www-authenticate'].startswith('Bearer')

    def test_the_key_own_header_is_accepted_without_a_deprecation_notice(
        self, client: TestClient, mcp_key: str
    ) -> None:
        """A client that can set a header uses X-API-Key, the non-deprecated form.

        Core marks a Bearer API key `Deprecation`; the endpoint honoured only
        Bearer, so every answer carried a notice telling the client's maintainer
        to switch to a header this endpoint refused. It accepts it now.
        """
        response = rpc(client, mcp_key, 'tools/list', own_header=True)

        assert response.status_code == 200, response.text
        assert 'deprecation' not in response.headers

    def test_a_key_without_the_use_permission_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
    ) -> None:
        from app.modules.mcp_server.tests.conftest import issue_key

        key = issue_key(db_session, mcp_org, mcp_user, permissions=['items:read'])

        response = rpc(client, key, 'tools/list')

        assert response.status_code == 401
        assert response.json()['detail']['code'] == 'MCP_PERMISSION_REQUIRED'

    def test_a_disabled_module_refuses_every_key(
        self,
        client: TestClient,
        db_session: Session,
        mcp_org: Organization,
        mcp_key: str,
    ) -> None:
        mcp_org.enabled_modules = ['core', 'items', 'locations', 'api_keys']
        db_session.commit()

        response = rpc(client, mcp_key, 'tools/list')

        assert response.status_code == 401
        assert response.json()['detail']['code'] == 'MCP_MODULE_DISABLED'

    def test_an_expired_key_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
    ) -> None:
        from app.modules.mcp_server.tests.conftest import issue_key

        key = issue_key(
            db_session,
            mcp_org,
            mcp_user,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        response = rpc(client, key, 'tools/list')

        assert response.status_code == 401

    def test_a_revoked_key_is_refused(
        self, client: TestClient, db_session: Session, mcp_key: str
    ) -> None:
        _revoke(db_session, mcp_key)

        response = rpc(client, mcp_key, 'tools/list')

        assert response.status_code == 401

    def test_a_key_whose_owner_left_the_organization_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        mcp_user: User,
        mcp_key: str,
    ) -> None:
        mcp_user.organization_id = None
        db_session.commit()

        response = rpc(client, mcp_key, 'tools/list')

        assert response.status_code == 401


class TestTransportSecurity:
    def test_a_foreign_host_is_refused(self, client: TestClient, mcp_key: str) -> None:
        response = rpc(client, mcp_key, 'tools/list', host='evil.example')

        assert response.status_code == 421

    def test_a_foreign_origin_is_refused(
        self, client: TestClient, mcp_key: str
    ) -> None:
        response = rpc(client, mcp_key, 'tools/list', origin='http://evil.example')

        assert response.status_code == 403

    def test_a_configured_origin_is_accepted(
        self, client: TestClient, mcp_key: str
    ) -> None:
        response = rpc(client, mcp_key, 'tools/list', origin='http://allowed.example')

        assert response.status_code == 200, response.text


class TestTheWire:
    def test_tools_list_answers_the_2026_07_28_revision(
        self, client: TestClient, mcp_key: str
    ) -> None:
        response = rpc(client, mcp_key, 'tools/list')

        assert response.status_code == 200, response.text
        result = response.json()['result']
        assert result['resultType'] == 'complete'
        assert result['cacheScope'] == 'private'
        assert [tool['name'] for tool in result['tools']] == [
            'search_items',
            'get_item',
            'list_locations',
            'get_location_tree',
            'get_stock_levels',
            'list_lots',
            'get_expiring_soon',
            'create_item',
            'correct_stock',
        ]

    def test_the_read_tools_are_read_only_and_the_writes_say_so(
        self, client: TestClient, mcp_key: str
    ) -> None:
        tools = {
            tool['name']: tool
            for tool in rpc(client, mcp_key, 'tools/list').json()['result']['tools']
        }
        read_names = [
            'search_items',
            'get_item',
            'list_locations',
            'get_location_tree',
            'get_stock_levels',
            'list_lots',
            'get_expiring_soon',
        ]

        assert all(tools[name]['annotations']['readOnlyHint'] for name in read_names)
        assert tools['create_item']['annotations'].get('readOnlyHint') is not True
        assert tools['create_item']['annotations']['destructiveHint'] is False
        assert tools['correct_stock']['annotations']['destructiveHint'] is True

    def test_a_mismatched_method_header_is_a_protocol_error(
        self, client: TestClient, mcp_key: str
    ) -> None:
        response = client.post(
            _PATH,
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/list',
                'params': {'_meta': _META},
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {mcp_key}',
                'Mcp-Protocol-Version': _PROTOCOL,
                'Mcp-Method': 'tools/call',
            },
        )

        assert response.status_code == 400
        assert response.json()['error']['code'] == -32020

    def test_the_endpoint_keeps_the_app_security_headers(
        self, client: TestClient, mcp_key: str
    ) -> None:
        response = rpc(client, mcp_key, 'tools/list')

        assert response.headers['x-content-type-options'] == 'nosniff'


class TestTheAuditActor:
    def test_the_request_is_recorded_as_the_key(
        self,
        client: TestClient,
        mcp_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The journal has to name the key, not only its owner."""
        from app.modules.mcp_server.router import _auth_app as auth

        seen: dict[str, object] = {}

        async def probe(scope, receive, send):
            seen['actor'] = current_actor()
            from starlette.responses import JSONResponse

            await JSONResponse({'ok': True})(scope, receive, send)

        monkeypatch.setattr(auth, 'app', probe)

        response = rpc(client, mcp_key, 'tools/list')

        assert response.status_code == 200
        assert seen['actor'] == {
            'type': 'api_key',
            'key_prefix': mcp_key[:15],
        }


class TestTheModulePermission:
    def test_the_manifest_declares_the_permission_the_gate_checks(self) -> None:
        import json
        from pathlib import Path

        manifest = json.loads(
            (Path(__file__).resolve().parents[2] / 'manifest.json').read_text('utf-8')
        )
        permissions = {entry['key']: entry for entry in manifest['permissions']}

        assert 'mcp_server:use' in permissions
        assert permissions['mcp_server:use']['default_roles'] == [
            'manager',
            'user',
            'viewer',
        ]


class TestTheRateLimit:
    def test_the_app_level_limit_keys_the_mounted_endpoint(
        self,
        client: TestClient,
        mcp_key: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The default limit reaches a mount, and the key is the bucket.

        The limiter is off for the suite; switching it on for one test is what
        measures the endpoint rather than the middleware's unit test.
        """
        from app.config import settings
        from app.core.limiter import limiter

        monkeypatch.setattr(limiter, 'enabled', True)
        monkeypatch.setattr(settings, 'RATE_LIMIT_PER_IP', '2/minute')

        assert rpc(client, mcp_key, 'tools/list').status_code == 200
        assert rpc(client, mcp_key, 'tools/list').status_code == 200
        refused = rpc(client, mcp_key, 'tools/list')

        assert refused.status_code == 429
        assert refused.json()['detail']['code'] == 'RATE_LIMIT_EXCEEDED'
