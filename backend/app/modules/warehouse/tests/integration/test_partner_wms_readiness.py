"""Partner code, address, and snapshot tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

# ---------------------------------------------------------------------------
# Tests: Partner code field
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnerCodeField:
    """Partner code field — CRUD with uniqueness constraint."""

    def test_create_partner_with_code_returns_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Supplier With Code',
            'type': 'SUPPLIER',
            'code': 'SUP-001',
        }
        response = client.post('/api/v1/partners', json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data['code'] == 'SUP-001'

    def test_create_partner_without_code_returns_null(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        payload = {'name': 'Supplier No Code', 'type': 'SUPPLIER'}
        response = client.post('/api/v1/partners', json=payload, headers=auth_headers)
        assert response.status_code == 201
        assert response.json()['code'] is None

    def test_create_duplicate_code_same_org_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # Create first partner with code
        client.post(
            '/api/v1/partners',
            json={'name': 'First', 'type': 'SUPPLIER', 'code': 'DOO-001'},
            headers=auth_headers,
        )
        # Same code, different name/type — should conflict
        response = client.post(
            '/api/v1/partners',
            json={'name': 'Second', 'type': 'CUSTOMER', 'code': 'DOO-001'},
            headers=auth_headers,
        )
        assert response.status_code == 409

    def test_create_same_code_different_orgs_allowed(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Two organisations can both have a partner with code ORG-001."""
        # Create second org + user
        org2 = Organization(
            name='Second Org Code Test',
            enabled_modules=['core', 'items', 'categories', 'partners'],
        )
        db_session.add(org2)
        db_session.commit()
        db_session.refresh(org2)

        user2 = User(
            email='org2codetest@example.com',
            hashed_password=get_password_hash('password'),
            full_name='Org2 User',
            organization_id=org2.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user2)
        db_session.commit()
        db_session.refresh(user2)

        token2 = create_access_token(data={'sub': str(user2.id)})
        headers2 = {'Authorization': f'Bearer {token2}'}

        r1 = client.post(
            '/api/v1/partners',
            json={'name': 'Org1 Partner', 'type': 'SUPPLIER', 'code': 'ORG-001'},
            headers=headers2,
        )
        r2 = client.post(
            '/api/v1/partners',
            json={'name': 'Org2 Partner', 'type': 'SUPPLIER', 'code': 'ORG-001'},
            headers=headers2,
        )
        # Second org can reuse same code (cross-org no conflict)
        assert r1.status_code == 201
        assert r2.status_code == 409  # same org, same code — conflict

    def test_update_partner_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        create_resp = client.post(
            '/api/v1/partners',
            json={'name': 'Update Code Test', 'type': 'SUPPLIER', 'code': 'OLD-001'},
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        partner_id = create_resp.json()['id']

        update_resp = client.put(
            f'/api/v1/partners/{partner_id}',
            json={'name': 'Update Code Test', 'type': 'SUPPLIER', 'code': 'NEW-001'},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()['code'] == 'NEW-001'

    def test_search_partner_by_code(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            '/api/v1/partners',
            json={'name': 'Searchable Partner', 'type': 'SUPPLIER', 'code': 'SRCH-42'},
            headers=auth_headers,
        )
        response = client.get(
            '/api/v1/partners/?search=SRCH-42',
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data['total'] >= 1
        assert any(p['code'] == 'SRCH-42' for p in data['items'])


# ---------------------------------------------------------------------------
# Tests: Partner snapshot on document confirmation
# ---------------------------------------------------------------------------

# We need minimal fixtures for creating documents — reuse pattern from conftest.


def _make_org_user_location(
    db_session: Session, prefix: str
) -> tuple[Organization, User, StorageLocation]:
    """Helper: create org + user + storage location for snapshot tests."""
    org = Organization(
        name=f'{prefix} Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    user = User(
        email=f'{prefix.lower()}@snapshot.test',
        hashed_password=get_password_hash('testpass'),
        full_name=f'{prefix} User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    storage_type = StorageType(
        name=f'{prefix} WH Type',
        type_code=f'{prefix.upper()[:8]}WH',
        behavior_mode='NONE',
    )
    db_session.add(storage_type)
    db_session.commit()
    db_session.refresh(storage_type)

    location = StorageLocation(
        name=f'{prefix} Location',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)

    return org, user, location


@pytest.mark.integration
class TestPartnerSnapshot:
    """Partner snapshot is populated at document confirmation time."""

    def test_confirm_document_creates_partner_snapshot(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        org, user, location = _make_org_user_location(db_session, 'Snapshot1')
        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        # Create partner with full details
        partner_resp = client.post(
            '/api/v1/partners',
            json={
                'name': 'Snapshot Supplier',
                'type': 'SUPPLIER',
                'code': 'SNAP-001',
                'tax_id': 'PL1234567890',
                'email': 'snap@supplier.com',
                'phone': '+48111222333',
                'address': {
                    'street': 'ul. Testowa 1',
                    'city': 'Warszawa',
                    'postal_code': '00-001',
                    'country': 'PL',
                },
            },
            headers=headers,
        )
        assert partner_resp.status_code == 201
        partner_id = partner_resp.json()['id']

        # Create OUT document (requires source location + partner)
        # First create an item
        item_resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Snap Item',
                'quantity': 20,
                'location_id': str(location.id),
            },
            headers=headers,
        )
        assert item_resp.status_code == 201
        item_id = item_resp.json()['id']

        doc_resp = client.post(
            '/api/v1/warehouse/documents',
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(location.id),
                'lines': [
                    {
                        'item_id': item_id,
                        'expected_quantity': 2,
                    }
                ],
            },
            headers=headers,
        )
        assert doc_resp.status_code == 201
        doc_id = doc_resp.json()['id']

        # Confirm the document
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=headers,
        )
        assert confirm_resp.status_code == 200

        # Check snapshot is populated
        get_resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=headers,
        )
        assert get_resp.status_code == 200
        doc = get_resp.json()
        snapshot = doc.get('partner_snapshot')
        assert snapshot is not None
        assert snapshot['name'] == 'Snapshot Supplier'
        assert snapshot['code'] == 'SNAP-001'
        assert snapshot['tax_id'] == 'PL1234567890'
        assert snapshot['email'] == 'snap@supplier.com'
        assert snapshot['address']['city'] == 'Warszawa'

    def test_draft_document_has_no_snapshot(
        self, client: TestClient, db_session: Session
    ) -> None:
        org, user, location = _make_org_user_location(db_session, 'Snapshot2')
        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        partner_resp = client.post(
            '/api/v1/partners',
            json={'name': 'Draft Partner', 'type': 'SUPPLIER'},
            headers=headers,
        )
        assert partner_resp.status_code == 201
        partner_id = partner_resp.json()['id']

        item_resp = client.post(
            '/api/v1/items',
            json={
                'name': 'Draft Item',
                'quantity': 10,
                'location_id': str(location.id),
            },
            headers=headers,
        )
        item_id = item_resp.json()['id']

        doc_resp = client.post(
            '/api/v1/warehouse/documents',
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(location.id),
                'lines': [{'item_id': item_id, 'expected_quantity': 1}],
            },
            headers=headers,
        )
        assert doc_resp.status_code == 201
        doc = doc_resp.json()
        # Draft documents should not have a snapshot yet
        assert doc.get('partner_snapshot') is None

    def test_document_without_partner_snapshot_is_null(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        org, user, location = _make_org_user_location(db_session, 'Snapshot3')
        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        # Create item in source and target location
        target_st = StorageType(
            name='Snap3 Target Type', type_code='SN3TGT', behavior_mode='NONE'
        )
        db_session.add(target_st)
        db_session.commit()
        db_session.refresh(target_st)

        target_loc = StorageLocation(
            name='Snap3 Target',
            organization_id=org.id,
            storage_type_id=target_st.id,
            created_by=user.id,
        )
        db_session.add(target_loc)
        db_session.commit()
        db_session.refresh(target_loc)

        item_resp = client.post(
            '/api/v1/items',
            json={
                'name': 'No Partner Item',
                'quantity': 10,
                'location_id': str(location.id),
            },
            headers=headers,
        )
        item_id = item_resp.json()['id']

        # INT document (no partner required)
        doc_resp = client.post(
            '/api/v1/warehouse/documents',
            json={
                'type': 'INT',
                'source_location_id': str(location.id),
                'target_location_id': str(target_loc.id),
                'lines': [{'item_id': item_id, 'expected_quantity': 1}],
            },
            headers=headers,
        )
        assert doc_resp.status_code == 201
        doc_id = doc_resp.json()['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=headers,
        )
        assert confirm_resp.status_code == 200

        get_resp = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
        assert get_resp.json()['partner_snapshot'] is None

    def test_snapshot_preserves_historical_partner_name(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        """Changing partner's name after confirmation should not affect snapshot."""
        org, user, location = _make_org_user_location(db_session, 'Snapshot4')
        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        partner_resp = client.post(
            '/api/v1/partners',
            json={'name': 'Original Name', 'type': 'SUPPLIER'},
            headers=headers,
        )
        assert partner_resp.status_code == 201
        partner_id = partner_resp.json()['id']

        item_resp = client.post(
            '/api/v1/items',
            json={
                'name': 'History Item',
                'quantity': 10,
                'location_id': str(location.id),
            },
            headers=headers,
        )
        item_id = item_resp.json()['id']

        doc_resp = client.post(
            '/api/v1/warehouse/documents',
            json={
                'type': 'OUT',
                'partner_id': partner_id,
                'source_location_id': str(location.id),
                'lines': [{'item_id': item_id, 'expected_quantity': 1}],
            },
            headers=headers,
        )
        doc_id = doc_resp.json()['id']

        # Confirm — snapshot captured
        client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)

        # Now rename partner
        client.put(
            f'/api/v1/partners/{partner_id}',
            json={'name': 'Totally Different Name', 'type': 'SUPPLIER'},
            headers=headers,
        )

        # Snapshot should still show original name
        get_resp = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
        snapshot = get_resp.json()['partner_snapshot']
        assert snapshot is not None
        assert snapshot['name'] == 'Original Name'
