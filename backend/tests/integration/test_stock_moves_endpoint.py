"""Integration tests for the StockMove movement history endpoint.

Endpoint: GET /api/v1/stock-moves
Filters: product_template_id, limit

Covers:
- happy path: StockMove records are returned for the product template
- org isolation (one org's moves never leak to another)
- empty result for an unknown product template
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def moves_org(db_session: Session) -> Organization:
    org = Organization(
        name='Moves Endpoint Org',
        enabled_modules=['core', 'warehouse'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def moves_user(db_session: Session, moves_org: Organization) -> User:
    user = User(
        email=f'moves-{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Moves User',
        organization_id=moves_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def moves_headers(moves_user: User) -> dict[str, str]:
    return _auth(moves_user)


@pytest.fixture
def moves_storage(
    db_session: Session, moves_org: Organization, moves_user: User
) -> StorageLocation:
    storage_type = StorageType(name='Moves Storage', type_code='MOVES')
    db_session.add(storage_type)
    db_session.flush()
    loc = StorageLocation(
        organization_id=moves_org.id,
        created_by=moves_user.id,
        storage_type_id=storage_type.id,
        name='Moves Loc',
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def moves_template(db_session: Session, moves_org: Organization) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=moves_org.id,
        name='Moves Template',
        sku=f'SKU-MV-{uuid4().hex[:8]}',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _create_moves_sync(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    storage_id: UUID,
    count: int = 3,
) -> list[StockMove]:
    """Create StockMove rows directly via the model + add (not via async API)."""
    moves = []
    for qty in (1, 2, 3)[:count]:
        m = StockMove(
            organization_id=org_id,
            product_template_id=template_id,
            from_location_id=None,
            to_location_id=storage_id,
            quantity=Decimal(qty),
            state='done',
            reference_type='item',
            reference_id=uuid4(),
        )
        db_session.add(m)
        moves.append(m)
    db_session.commit()
    return moves


@pytest.mark.integration
class TestStockMovesEndpoint:
    """GET /api/v1/stock-moves."""

    def test_returns_moves_for_product_template(
        self,
        client: TestClient,
        db_session: Session,
        moves_headers: dict[str, str],
        moves_org: Organization,
        moves_template: ProductTemplate,
        moves_storage: StorageLocation,
    ) -> None:
        _create_moves_sync(
            db_session,
            moves_org.id,
            moves_template.id,
            moves_storage.id,
            count=3,
        )

        response = client.get(
            '/api/v1/stock-moves',
            params={'product_template_id': str(moves_template.id)},
            headers=moves_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        moves = response.json()['items']
        assert len(moves) == 3
        assert all(m['product_template_id'] == str(moves_template.id) for m in moves)
        quantities = sorted(Decimal(m['quantity']) for m in moves)
        assert quantities == [Decimal('1'), Decimal('2'), Decimal('3')]

    def test_empty_for_unknown_product(
        self,
        client: TestClient,
        db_session: Session,
        moves_headers: dict[str, str],
        moves_template: ProductTemplate,
    ) -> None:
        response = client.get(
            '/api/v1/stock-moves',
            params={'product_template_id': str(uuid4())},
            headers=moves_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_org_isolation(
        self,
        client: TestClient,
        db_session: Session,
        moves_headers: dict[str, str],
        moves_user: User,
        moves_template: ProductTemplate,
        moves_storage: StorageLocation,
    ) -> None:
        """A second org's moves must not leak into the first org's response."""
        from app.models.organization import Organization

        other_org = Organization(
            name='Other Org',
            enabled_modules=['core', 'warehouse'],
        )
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        other_template = ProductTemplate(
            organization_id=other_org.id,
            name='Other Template',
            sku=f'SKU-OTH-{uuid4().hex[:8]}',
        )
        db_session.add(other_template)
        db_session.commit()
        db_session.refresh(other_template)

        other_loc = StorageLocation(
            organization_id=other_org.id,
            created_by=moves_user.id,
            storage_type_id=moves_storage.storage_type_id,
            name='Other Loc',
        )
        db_session.add(other_loc)
        db_session.commit()

        _create_moves_sync(
            db_session, other_org.id, other_template.id, other_loc.id, count=2
        )

        response = client.get(
            '/api/v1/stock-moves',
            params={'product_template_id': str(other_template.id)},
            headers=moves_headers,
        )
        # Empty: the test user is in moves_org, not other_org.
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_limit_caps_results(
        self,
        client: TestClient,
        db_session: Session,
        moves_headers: dict[str, str],
        moves_org: Organization,
        moves_template: ProductTemplate,
        moves_storage: StorageLocation,
    ) -> None:
        _create_moves_sync(
            db_session,
            moves_org.id,
            moves_template.id,
            moves_storage.id,
            count=5,
        )

        response = client.get(
            '/api/v1/stock-moves',
            params={
                'product_template_id': str(moves_template.id),
                'limit': 2,
            },
            headers=moves_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()['items']) == 2
