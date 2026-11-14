"""Fixtures for the MCP Server module's tests.

Every request authenticates with an API key, so the fixtures create the key as
a row (the issuing endpoint is another module's job): the endpoint and each tool
see exactly the key's own permission list.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.api_keys.models import ApiKey
from app.services.token_service import get_password_hash
from tests.integration._shelf import anchor_pending_records

KEY_PERMISSIONS = ['mcp_server:use', 'items:read', 'locations:read']


def _make_org(db: Session, name: str) -> Organization:
    org = Organization(
        name=name,
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'api_keys',
            'mcp_server',
        ],
        settings={
            'module:mcp_server': {
                'allowed_hosts': ['testserver'],
                'allowed_origins': ['http://allowed.example'],
            }
        },
    )
    db.add(org)
    db.flush()
    db.commit()
    db.refresh(org)
    return org


def _make_user(db: Session, org: Organization, label: str) -> User:
    user = User(
        email=f'mcp-{label}-{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('irrelevant'),
        full_name=f'MCP {label}',
        organization_id=org.id,
        role='user',
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.commit()
    db.refresh(user)
    return user


def issue_key(
    db: Session,
    org: Organization,
    user: User,
    *,
    permissions: list[str] | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Write one API key row and return the raw key the test sends."""
    raw = f'inv_live_{uuid4().hex[:16]}'
    db.add(
        ApiKey(
            organization_id=org.id,
            user_id=user.id,
            name='MCP test key',
            hashed_key=hashlib.sha256(raw.encode()).hexdigest(),
            key_prefix=raw[:15],
            permissions=KEY_PERMISSIONS if permissions is None else permissions,
            scope_names=[],
            is_active=True,
            expires_at=expires_at,
        )
    )
    db.flush()
    db.commit()
    return raw


@pytest.fixture
def mcp_org(db_session: Session) -> Organization:
    return _make_org(db_session, 'MCP Home')


@pytest.fixture
def mcp_user(db_session: Session, mcp_org: Organization) -> User:
    return _make_user(db_session, mcp_org, 'owner')


@pytest.fixture
def mcp_key(db_session: Session, mcp_org: Organization, mcp_user: User) -> str:
    return issue_key(db_session, mcp_org, mcp_user)


@pytest.fixture
def mcp_org_b(db_session: Session) -> Organization:
    return _make_org(db_session, 'MCP Elsewhere')


@pytest.fixture
def mcp_user_b(db_session: Session, mcp_org_b: Organization) -> User:
    return _make_user(db_session, mcp_org_b, 'other')


@pytest.fixture
def mcp_key_b(db_session: Session, mcp_org_b: Organization, mcp_user_b: User) -> str:
    return issue_key(db_session, mcp_org_b, mcp_user_b)


@pytest.fixture
def shelf(
    db_session: Session, mcp_org: Organization, mcp_user: User
) -> StorageLocation:
    location = StorageLocation(
        organization_id=mcp_org.id,
        created_by=mcp_user.id,
        name='Cold Storage A',
    )
    db_session.add(location)
    db_session.flush()
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture
def shelf_b(
    db_session: Session, mcp_org_b: Organization, mcp_user_b: User
) -> StorageLocation:
    location = StorageLocation(
        organization_id=mcp_org_b.id,
        created_by=mcp_user_b.id,
        name='Other Shelving',
    )
    db_session.add(location)
    db_session.flush()
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture
def lot(db_session: Session, mcp_org: Organization, shelf: StorageLocation) -> StockLot:
    from app.models.product_template import ProductTemplate

    product = ProductTemplate(organization_id=mcp_org.id, name='Olive Oil')
    db_session.add(product)
    db_session.flush()
    batch = StockLot(
        organization_id=mcp_org.id,
        product_template_id=product.id,
        name='LOT-OLIVE-1',
        expiry_date=date.today() + timedelta(days=2),
        status='active',
    )
    db_session.add(batch)
    db_session.flush()
    db_session.commit()
    db_session.refresh(batch)
    return batch


@pytest.fixture
def item(
    db_session: Session,
    mcp_org: Organization,
    shelf: StorageLocation,
    lot: StockLot,
) -> Item:
    record = Item(
        organization_id=mcp_org.id,
        storage_location_id=shelf.id,
        template_id=lot.product_template_id,
        lot_id=lot.id,
        name='Olive Oil',
        quantity=Decimal('5'),
        expiry_date=lot.expiry_date,
    )
    db_session.add(record)
    anchor_pending_records(db_session)
    db_session.flush()
    db_session.commit()
    db_session.refresh(record)
    return record


@pytest.fixture
def item_b(
    db_session: Session, mcp_org_b: Organization, shelf_b: StorageLocation
) -> Item:
    record = Item(
        organization_id=mcp_org_b.id,
        storage_location_id=shelf_b.id,
        name='Secret B Product',
        quantity=Decimal('9'),
    )
    db_session.add(record)
    anchor_pending_records(db_session)
    db_session.flush()
    db_session.commit()
    db_session.refresh(record)
    return record


_PROTOCOL = '2026-07-28'
_META = {
    'io.modelcontextprotocol/protocolVersion': _PROTOCOL,
    'io.modelcontextprotocol/clientCapabilities': {},
}


@pytest.fixture
def mcp_call(client):
    """POST one JSON-RPC request in the 2026-07-28 wire shape."""

    def call(
        key: str,
        method: str,
        *,
        params: dict | None = None,
        name: str | None = None,
        host: str | None = None,
    ):
        query = '/api/v1/mcp-server/mcp'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
            'Mcp-Protocol-Version': _PROTOCOL,
            'Mcp-Method': method,
        }
        if name is not None:
            headers['Mcp-Name'] = name
        if host is not None:
            headers['Host'] = host
        return client.post(
            query,
            json={
                'jsonrpc': '2.0',
                'id': 7,
                'method': method,
                'params': {**(params or {}), '_meta': _META},
            },
            headers=headers,
        )

    return call
