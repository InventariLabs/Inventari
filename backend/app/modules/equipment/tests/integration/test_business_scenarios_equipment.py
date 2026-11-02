"""
Business scenario integration tests for Equipment module.

Each test represents a realistic end-to-end business workflow executed through
the API. Tests cover asset lifecycle, maintenance, warranty alerts, attestation
campaigns, and protocol generation.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def bs_eq_org(db_session: Session) -> Organization:
    org = Organization(
        name='Equipment Scenario Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'equipment'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def bs_eq_user(db_session: Session, bs_eq_org: Organization) -> User:
    user = User(
        email='equipment-scenario@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Equipment Scenario User',
        organization_id=bs_eq_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def eq_headers(bs_eq_user: User) -> dict[str, str]:
    return _auth(bs_eq_user)


@pytest.fixture
def it_storage_type(db_session: Session) -> StorageType:
    st = StorageType(name='IT Storage', type_code='IT_STORAGE', behavior_mode='NONE')
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)
    return st


@pytest.fixture
def it_location(
    db_session: Session,
    bs_eq_org: Organization,
    it_storage_type: StorageType,
    bs_eq_user: User,
) -> StorageLocation:
    loc = StorageLocation(
        name='Server Room A',
        organization_id=bs_eq_org.id,
        storage_type_id=it_storage_type.id,
        created_by=bs_eq_user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def laptop_category(db_session: Session) -> Category:
    cat = Category(
        name='Laptop',
        code='LAPTOP',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[
            {
                'key': 'serial_number',
                'type': 'text',
                'label': 'Serial Number',
                'is_system': True,
            },
            {
                'key': 'warranty_until',
                'type': 'date',
                'label': 'Warranty Until',
                'is_system': True,
            },
            {
                'key': 'equipment_status',
                'type': 'select',
                'label': 'Status',
                'is_system': True,
                'options': ['AVAILABLE', 'DEPLOYED', 'MAINTENANCE', 'RETIRED'],
            },
        ],
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)
    return cat


@pytest.fixture
def laptop_item(
    db_session: Session,
    bs_eq_org: Organization,
    it_location: StorageLocation,
    laptop_category: Category,
) -> Item:
    item = Item(
        name='ThinkPad X1 Carbon',
        organization_id=bs_eq_org.id,
        storage_location_id=it_location.id,
        category_id=laptop_category.id,
        quantity=1,
        meta_data={
            'equipment': {
                'serial_number': 'SN-LAPTOP-001',
                'equipment_status': 'AVAILABLE',
            }
        },
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _create_equipment_item(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    category: Category,
    name: str,
    serial: str,
    meta_data: dict[str, Any] | None = None,
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data=meta_data
        or {'equipment': {'serial_number': serial, 'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestE1AssetLifecycle:
    """
    E1 — Asset Lifecycle: Create → Checkout → Checkin → Reassign

    Tests the full lifecycle: bulk create items, checkout, checkin, reassign,
    and verifies status transitions: AVAILABLE → DEPLOYED → AVAILABLE → DEPLOYED.
    """

    def test_full_lifecycle(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        bs_eq_org: Organization,
        it_location: StorageLocation,
        laptop_category: Category,
    ) -> None:
        # Step 1: Bulk-create 2 laptops
        resp = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_headers,
            json={
                'name': 'Dell Latitude',
                'category_id': str(laptop_category.id),
                'location_id': str(it_location.id),
                'entries': [
                    {'serial_number': 'SN-DELL-001'},
                    {'serial_number': 'SN-DELL-002'},
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data['created'] == 2
        item1_id = data['items'][0]

        # Step 2: Checkout item-1 to Alice
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={
                'item_id': item1_id,
                'assigned_to_name': 'Alice',
                'assigned_to_email': 'alice@test.com',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment1_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        # Step 3: Verify status == DEPLOYED
        resp = client.get(f'/api/v1/items/{item1_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['metadata']['equipment']['equipment_status'] == 'DEPLOYED'

        # Step 4: Checkin item-1 condition=GOOD
        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment1_id}/checkin',
            headers=eq_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['checkin_condition'] == 'GOOD'

        db_session.flush()
        db_session.expire_all()

        # Step 5: Verify status == AVAILABLE
        resp = client.get(f'/api/v1/items/{item1_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['metadata']['equipment']['equipment_status'] == 'AVAILABLE'

        # Step 6: Checkout item-1 to Bob
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={
                'item_id': item1_id,
                'assigned_to_name': 'Bob',
                'assigned_to_email': 'bob@test.com',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 7: Verify status == DEPLOYED
        resp = client.get(f'/api/v1/items/{item1_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['metadata']['equipment']['equipment_status'] == 'DEPLOYED'

        # Verify active assignment exists
        resp = client.get('/api/v1/equipment/assignments', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK
        active = [a for a in resp.json()['items'] if a['item_id'] == item1_id]
        assert len(active) == 1
        assert active[0]['assigned_to_name'] == 'Bob'
        assert active[0]['checked_in_at'] is None


@pytest.mark.integration
class TestE2DamagedReturnTriggersMaintenance:
    """
    E2 — Damaged Return Triggers Maintenance

    Tests that checking in equipment with DAMAGED condition sets status to MAINTENANCE,
    opens the service case the card's Maintenance tab shows, and that maintenance logs
    can be added and are reflected in dashboard.
    """

    def test_damaged_checkin_sets_maintenance(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        bs_eq_org: Organization,
        laptop_item: Item,
    ) -> None:
        item_id = str(laptop_item.id)

        # Step 1: Checkout to Alice
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={'item_id': item_id, 'assigned_to_name': 'Alice'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        # Step 2: Checkin condition=DAMAGED
        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_headers,
            json={'checkin_condition': 'DAMAGED', 'checkin_notes': 'Screen cracked'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 3: Verify equipment_status == MAINTENANCE
        resp = client.get(f'/api/v1/items/{item_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['metadata']['equipment']['equipment_status'] == 'MAINTENANCE'

        # Step 4: Add maintenance log - type=REPAIR, cost=150.00
        resp = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_headers,
            json={
                'item_id': item_id,
                'maintenance_type': 'REPAIR',
                'title': 'Screen replacement',
                'cost': '150.00',
                'currency': 'USD',
                'performed_at': str(date.today()),
                'performed_by': 'Tech Team',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        log_id = resp.json()['id']

        # Step 5: Verify log exists via history endpoint
        resp = client.get(
            f'/api/v1/equipment/maintenance/item/{item_id}', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        logs = resp.json()['items']
        assert len(logs) >= 1
        assert any(log['id'] == log_id for log in logs)

        # Step 6: Verify dashboard shows in_maintenance >= 1
        resp = client.get('/api/v1/equipment/dashboard', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        dashboard = resp.json()
        assert dashboard['in_maintenance'] >= 1

        # Step 7: Add second maintenance log - type=CLEANING
        resp = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_headers,
            json={
                'item_id': item_id,
                'maintenance_type': 'CLEANING',
                'title': 'Keyboard cleaning',
                'performed_at': str(date.today()),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        # Step 8: Verify history has the opening entry plus the two filings
        resp = client.get(
            f'/api/v1/equipment/maintenance/item/{item_id}', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        logs = resp.json()['items']
        # The damaged return already opened the service case, so the two
        # manual entries stand beside it rather than alone.
        assert len(logs) == 3


@pytest.mark.integration
class TestE3AssignmentInterceptorBlocksDeletion:
    """
    E3 — Assignment Interceptor Blocks Item Deletion

    Tests that the EquipmentItemInterceptor blocks deletion of items with
    active assignments (returns 422), and that after checkin deletion succeeds.
    """

    def test_delete_blocked_when_assigned(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        laptop_item: Item,
    ) -> None:
        item_id = str(laptop_item.id)

        # Step 1: Checkout to Alice
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={'item_id': item_id, 'assigned_to_name': 'Alice'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        # Step 2: DELETE while assigned → expect 409 (: state conflict)
        resp = client.delete(f'/api/v1/items/{item_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == 'EQUIPMENT_ASSIGNED'

        # Step 2b: retire is no longer a delete — it sets the RETIRED
        # status — but an asset someone still holds cannot leave the active
        # register either way, so it answers with the same 409 shape as the
        # delete above. Otherwise the asset would count as checked out and
        # retired at once, and the check-in below would silently un-retire it.
        resp = client.post(
            f'/api/v1/equipment/items/{item_id}/retire', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == 'EQUIPMENT_ASSIGNED'

        # Step 3: Checkin condition=GOOD
        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 4: DELETE after checkin → expect 204
        resp = client.delete(f'/api/v1/items/{item_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.text

        # Step 5: Verify item no longer exists
        resp = client.get(f'/api/v1/items/{item_id}', headers=eq_headers)
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text


@pytest.mark.integration
class TestE4WarrantyAlertsAndDashboard:
    """
    E4 — Warranty Alerts & Dashboard Aggregation

    Tests that the dashboard correctly aggregates items by status, and that
    warranty alerts correctly filter items expiring within the specified window.
    """

    def test_warranty_alerts_and_dashboard(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        bs_eq_org: Organization,
        it_location: StorageLocation,
        laptop_category: Category,
        bs_eq_user: User,
    ) -> None:
        today = date.today()
        yesterday = today - timedelta(days=1)
        in_15_days = today + timedelta(days=15)
        in_365_days = today + timedelta(days=365)

        # Create 3 items with different warranty dates
        _create_equipment_item(
            db_session,
            bs_eq_org,
            it_location,
            laptop_category,
            'Laptop A - Expired',
            'SN-A-EXP',
            meta_data={
                'equipment': {
                    'serial_number': 'SN-A-EXP',
                    'equipment_status': 'AVAILABLE',
                    'warranty_until': yesterday.isoformat(),
                }
            },
        )
        item_b = _create_equipment_item(
            db_session,
            bs_eq_org,
            it_location,
            laptop_category,
            'Laptop B - 15 days',
            'SN-B-15D',
            meta_data={
                'equipment': {
                    'serial_number': 'SN-B-15D',
                    'equipment_status': 'AVAILABLE',
                    'warranty_until': in_15_days.isoformat(),
                }
            },
        )
        item_c = _create_equipment_item(
            db_session,
            bs_eq_org,
            it_location,
            laptop_category,
            'Laptop C - 365 days',
            'SN-C-365D',
            meta_data={
                'equipment': {
                    'serial_number': 'SN-C-365D',
                    'equipment_status': 'AVAILABLE',
                    'warranty_until': in_365_days.isoformat(),
                }
            },
        )

        db_session.flush()
        db_session.expire_all()

        # Step 2: GET dashboard
        resp = client.get('/api/v1/equipment/dashboard', headers=eq_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        dashboard = resp.json()

        # Assertions for dashboard
        assert dashboard['total_assets'] == 3
        assert dashboard['by_status'].get('AVAILABLE', 0) == 3

        # Step 3: GET warranty alerts with days=30
        resp = client.get(
            '/api/v1/equipment/warranty-alerts?days=30', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        alerts = resp.json()['items']

        # Item B (15 days) should be in alerts
        alert_ids = [a['item_id'] for a in alerts]
        assert str(item_b.id) in alert_ids

        # Item C (365 days) should NOT be in alerts
        assert str(item_c.id) not in alert_ids

        # Alerts should be sorted by days_remaining ascending
        if len(alerts) >= 2:
            assert alerts[0]['days_remaining'] <= alerts[1]['days_remaining']


@pytest.mark.integration
class TestE5AssignmentHistoryAuditTrail:
    """
    E5 — Full Assignment History Audit Trail

    Tests that the assignment history endpoint returns complete records of
    all checkouts and checkins, with correct assignee and condition data.
    """

    def test_assignment_history_complete(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        laptop_item: Item,
    ) -> None:
        item_id = str(laptop_item.id)

        # Step 1: Checkout to Alice, checkin GOOD
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={'item_id': item_id, 'assigned_to_name': 'Alice'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment1_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment1_id}/checkin',
            headers=eq_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 2: Checkout to Bob, checkin DAMAGED
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={'item_id': item_id, 'assigned_to_name': 'Bob'},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment2_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment2_id}/checkin',
            headers=eq_headers,
            json={'checkin_condition': 'DAMAGED'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 3: GET assignment history
        resp = client.get(
            f'/api/v1/equipment/assignments/item/{item_id}', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        history = resp.json()['items']

        # Assertions
        assert len(history) == 2

        # First assignment: Alice, GOOD condition
        first = next(a for a in history if a['assigned_to_name'] == 'Alice')
        assert first['checkin_condition'] == 'GOOD'
        assert first['checked_in_at'] is not None

        # Second assignment: Bob, DAMAGED condition
        second = next(a for a in history if a['assigned_to_name'] == 'Bob')
        assert second['checkin_condition'] == 'DAMAGED'
        assert second['checked_in_at'] is not None

        # Timestamps: second.checked_out_at > first.checked_in_at
        assert second['checked_out_at'] > first['checked_in_at']


@pytest.mark.integration
class TestE6AttestationCampaignLaunchConfirmComplete:
    """
    E6 — Attestation Campaign: Launch → Confirm → Complete

    Tests the full attestation campaign lifecycle:
    DRAFT → ACTIVE → CONFIRMED → COMPLETED
    with token-based public access and idempotent confirm.
    """

    def test_campaign_lifecycle(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        laptop_item: Item,
    ) -> None:
        item_id = str(laptop_item.id)
        alice_email = 'alice@test.com'

        # Step 1: Checkout to Alice with email
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={
                'item_id': item_id,
                'assigned_to_name': 'Alice',
                'assigned_to_email': alice_email,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 2: Create campaign - scope_type=ALL, deadline=7 days
        deadline = datetime.now(UTC) + timedelta(days=7)
        resp = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_headers,
            json={
                'name': 'Q1 Asset Audit',
                'scope_type': 'ALL',
                'deadline': deadline.isoformat(),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        campaign_id = resp.json()['id']
        assert resp.json()['status'] == 'DRAFT'

        # Step 4: Launch campaign
        resp = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Step 5: Verify status=ACTIVE (launch always transitions, email failure is logged)
        resp = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'ACTIVE'

        # Get token directly from database
        from app.modules.equipment.models import AuditResponse

        audit_response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).first()
        assert audit_response is not None, 'AuditResponse should be created'
        token = audit_response.token

        # Step 6: GET public attestation with token → status=PENDING
        resp = client.get(f'/public/attestation/{token}')
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'PENDING'

        # Step 7: POST confirm → status=CONFIRMED
        resp = client.post(f'/public/attestation/{token}/confirm')
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'CONFIRMED'

        # Step 8: Idempotent confirm again → still CONFIRMED
        resp = client.post(f'/public/attestation/{token}/confirm')
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'CONFIRMED'

        # Step 10: Complete campaign
        resp = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'COMPLETED'

        # Verify stats
        resp = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        stats = resp.json()['stats']
        assert stats['total'] == 1
        assert stats['confirmed'] == 1


@pytest.mark.integration
class TestE7AttestationCampaignDisputePath:
    """
    E7 — Attestation Campaign: Dispute Path

    Tests that a campaign assignee can dispute an assignment with
    a dispute_type and reason, and that stats correctly reflect disputed status.
    """

    def test_campaign_dispute_path(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        laptop_item: Item,
    ) -> None:
        item_id = str(laptop_item.id)
        alice_email = 'alice@test.com'

        # Setup: checkout to Alice
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={
                'item_id': item_id,
                'assigned_to_name': 'Alice',
                'assigned_to_email': alice_email,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        db_session.flush()
        db_session.expire_all()

        # Create and launch campaign
        deadline = datetime.now(UTC) + timedelta(days=7)
        resp = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_headers,
            json={
                'name': 'Dispute Test Campaign',
                'scope_type': 'ALL',
                'deadline': deadline.isoformat(),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        campaign_id = resp.json()['id']

        # Launch (email failure is logged, campaign still transitions to ACTIVE)
        resp = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.flush()
        db_session.expire_all()

        # Get token directly from database
        from app.modules.equipment.models import AuditResponse

        audit_response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).first()
        assert audit_response is not None, 'AuditResponse should be created'
        token = audit_response.token

        # Step 2: Get attestation page (PENDING)
        resp = client.get(f'/public/attestation/{token}')
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'PENDING'

        # Step 3: POST dispute with type and reason
        resp = client.post(
            f'/public/attestation/{token}/dispute',
            json={'dispute_type': 'MISSING', 'reason': 'Nie mam tego sprzętu'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        dispute_data = resp.json()
        assert dispute_data['status'] == 'DISPUTED'
        assert dispute_data['dispute_type'] == 'MISSING'
        assert dispute_data['dispute_reason'] == 'Nie mam tego sprzętu'

        # Verify campaign stats show disputed
        resp = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        stats = resp.json()['stats']
        assert stats['disputed'] == 1
        assert stats['confirmed'] == 0


@pytest.mark.integration
class TestE8ProtocolGenerationHTML:
    """
    E8 — Protocol Generation (HTML)

    Tests that the protocol HTML endpoint returns valid HTML containing
    the assignee name, item name, organization, and document reference.
    """

    def test_protocol_html_contains_expected_content(
        self,
        client: TestClient,
        eq_headers: dict[str, str],
        db_session: Session,
        laptop_item: Item,
        bs_eq_org: Organization,
    ) -> None:
        item_id = str(laptop_item.id)

        # Step 1: Checkout item to Alice with notes
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_headers,
            json={
                'item_id': item_id,
                'assigned_to_name': 'Alice',
                'assigned_to_email': 'alice@test.com',
                'checkout_notes': 'Przekazanie laptopa',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assignment_id = resp.json()['id']

        db_session.flush()
        db_session.expire_all()

        # Step 2: GET protocol HTML
        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert 'text/html' in resp.headers.get('content-type', '')

        html_content = resp.text

        # Step 3: Assertions for HTML content
        assert 'Alice' in html_content, 'HTML should contain assignee name'
        assert (
            'ThinkPad X1 Carbon' in html_content or 'laptop' in html_content.lower()
        ), 'HTML should contain item name'
        assert bs_eq_org.name in html_content, 'HTML should contain organization name'

        # Document reference pattern: EQ-YYYYMMDD-XXXXXXXX
        import re

        doc_ref_pattern = r'EQ-\d{8}-[A-Z0-9]+'
        assert re.search(doc_ref_pattern, html_content), (
            'HTML should contain document reference matching EQ-YYYYMMDD-XXXXXXXX'
        )
