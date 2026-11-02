"""
Integration tests: equipment actions trigger webhook delivery.

Tests verify:
- GET /api/v1/webhooks/events includes equipment.checkout and equipment.checkin
- equipment.checkout event fires and creates a WebhookDeliveryLog on checkout
- equipment.checkin event fires and creates a WebhookDeliveryLog on checkin
- Payload content is correct (item_id, assigned_to_name, event name)
- Org B webhook is NOT triggered by Org A equipment action (tenant isolation)
- No webhook endpoint registered → no delivery log created (fast path)

Note on test architecture:
``_make_event_handler`` (called via the live EventBus) creates its own
session via ``SessionLocal()``.  In tests the conftest patches
``settings.DATABASE_URL`` *after* ``database.py`` has already been imported,
so that session connects to the production DB rather than the test DB and
cannot see fixture data.  The delivery-log assertions therefore call
``dispatch_event`` directly with the test ``db_session`` so that all fixture
data is visible and delivery logs land in the same transaction.
"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.events import TenantEventPayload
from app.models.item import Item
from app.models.organization import Organization
from app.models.user import User
from app.modules.equipment.events import EquipmentEvent
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.webhook_service import dispatch_event
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _run_dispatch(event: EquipmentEvent, payload: TenantEventPayload) -> None:
    """Run ``dispatch_event`` synchronously in a fresh event loop.

    The subscriber opens its own sessions; a pooled engine hands it
    connections bound to whichever loop it first served, so the subscriber
    gets a throwaway NullPool engine over the test database for this one
    call. A new loop is used to avoid interfering with the TestClient's own.
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from app import database as app_database
    from app.config import settings

    async_url = settings.DATABASE_URL.replace(
        'postgresql://', 'postgresql+asyncpg://', 1
    )
    engine = create_async_engine(async_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # db_facade forwards live
        with patch.object(app_database, 'AsyncSessionLocal', factory):
            loop.run_until_complete(dispatch_event(event, payload))
    finally:
        loop.run_until_complete(engine.dispose())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        asyncio.set_event_loop(None)
        loop.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def eq_org_with_webhooks(db_session: Session) -> Organization:
    """Organization with both equipment and webhooks modules enabled."""
    org = Organization(
        name='Equipment + Webhooks Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'equipment',
            'webhooks',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def ew_user(db_session: Session, eq_org_with_webhooks: Organization) -> User:
    user = User(
        email='ew_user@example.com',
        hashed_password=get_password_hash('pass123'),
        full_name='EW User',
        organization_id=eq_org_with_webhooks.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def ew_headers(ew_user: User) -> dict[str, str]:
    token = create_access_token(data={'sub': str(ew_user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def ew_item(
    db_session: Session, eq_org_with_webhooks: Organization, ew_user: User
) -> object:
    """Minimal equipment item in the combined org."""
    from app.models.category import Category
    from app.models.item import Item
    from app.models.storage_location import StorageLocation
    from app.models.storage_type import StorageType

    st = StorageType(
        name='IT EW Storage', type_code='IT_EW_STORAGE', behavior_mode='NONE'
    )
    db_session.add(st)
    db_session.commit()

    loc = StorageLocation(
        name='EW Room',
        organization_id=eq_org_with_webhooks.id,
        storage_type_id=st.id,
        created_by=ew_user.id,
    )
    db_session.add(loc)
    db_session.commit()

    cat = Category(
        name='Laptop EW',
        code='LAPTOP_EW',
        context_tag='equipment',
        organization_id=None,
    )
    db_session.add(cat)
    db_session.commit()

    item = Item(
        name='Dell XPS EW',
        organization_id=eq_org_with_webhooks.id,
        storage_location_id=loc.id,
        category_id=cat.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def checkout_webhook(
    db_session: Session, eq_org_with_webhooks: Organization
) -> WebhookEndpoint:
    """Active webhook subscribed to equipment.checkout."""
    ep = WebhookEndpoint(
        organization_id=eq_org_with_webhooks.id,
        name='Checkout Listener',
        url='https://listener.example.com/hook',
        http_method='POST',
        event_types=['equipment.checkout'],
        max_retries=0,
        timeout_seconds=5,
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()
    db_session.refresh(ep)
    return ep


@pytest.fixture
def checkin_webhook(
    db_session: Session, eq_org_with_webhooks: Organization
) -> WebhookEndpoint:
    """Active webhook subscribed to equipment.checkin."""
    ep = WebhookEndpoint(
        organization_id=eq_org_with_webhooks.id,
        name='Checkin Listener',
        url='https://listener.example.com/checkin',
        http_method='POST',
        event_types=['equipment.checkin'],
        max_retries=0,
        timeout_seconds=5,
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()
    db_session.refresh(ep)
    return ep


# ---------------------------------------------------------------------------
# Helper: fake successful HTTP delivery
# ---------------------------------------------------------------------------

_MOCK_OK_RESPONSE = AsyncMock(
    status_code=200,
    text='OK',
)


# ---------------------------------------------------------------------------
# Tests: event catalogue
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEquipmentEventsInCatalogue:
    """equipment.checkout and equipment.checkin must appear in /webhooks/events."""

    def test_equipment_checkout_event_listed(
        self, client: TestClient, ew_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/webhooks/events', headers=ew_headers)
        assert response.status_code == status.HTTP_200_OK
        event_types = [e['event_type'] for e in response.json()]
        assert 'equipment.checkout' in event_types

    def test_equipment_checkin_event_listed(
        self, client: TestClient, ew_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/webhooks/events', headers=ew_headers)
        assert response.status_code == status.HTTP_200_OK
        event_types = [e['event_type'] for e in response.json()]
        assert 'equipment.checkin' in event_types


# ---------------------------------------------------------------------------
# Tests: checkout → delivery log created
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCheckoutWebhookDispatch:
    """Checking out an asset fires equipment.checkout to matching endpoints."""

    def test_checkout_creates_delivery_log(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        ew_user: User,
        checkout_webhook: WebhookEndpoint,
        db_session: Session,
    ) -> None:
        """After checkout, a delivery log with event_type=equipment.checkout exists."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=ew_headers,
            json={'item_id': str(ew_item.id), 'assigned_to_name': 'Tomek Nowak'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assignment_id = response.json()['id']

        payload = TenantEventPayload(
            organization_id=str(ew_item.organization_id),
            assignment_id=assignment_id,
            item_id=str(ew_item.id),
            item_name=ew_item.name,
            assigned_to_name='Tomek Nowak',
            user_id=str(ew_user.id),
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            _run_dispatch(EquipmentEvent.CHECKOUT, payload)

        logs = list(
            db_session.scalars(
                select(WebhookDeliveryLog).where(
                    WebhookDeliveryLog.webhook_endpoint_id == checkout_webhook.id,
                    WebhookDeliveryLog.event_type == 'equipment.checkout',
                )
            ).all()
        )
        assert len(logs) == 1

    def test_checkout_payload_contains_item_and_assignee(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        ew_user: User,
        checkout_webhook: WebhookEndpoint,
        db_session: Session,
    ) -> None:
        """Delivery log payload includes item_id and assigned_to_name."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=ew_headers,
            json={'item_id': str(ew_item.id), 'assigned_to_name': 'Anna Kowalska'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assignment_id = response.json()['id']

        payload = TenantEventPayload(
            organization_id=str(ew_item.organization_id),
            assignment_id=assignment_id,
            item_id=str(ew_item.id),
            item_name=ew_item.name,
            assigned_to_name='Anna Kowalska',
            user_id=str(ew_user.id),
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            _run_dispatch(EquipmentEvent.CHECKOUT, payload)

        log = db_session.scalars(
            select(WebhookDeliveryLog).where(
                WebhookDeliveryLog.webhook_endpoint_id == checkout_webhook.id
            )
        ).first()
        assert log is not None
        assert log.event_type == 'equipment.checkout'
        payload_data = log.payload_json.get('data', {})
        assert payload_data.get('item_id') == str(ew_item.id)
        assert payload_data.get('assigned_to_name') == 'Anna Kowalska'

    def test_no_webhook_registered_no_delivery_log(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        db_session: Session,
    ) -> None:
        """Without a registered webhook, no delivery logs are created."""
        before_count = db_session.scalar(select(func.count(WebhookDeliveryLog.id)))

        client.post(
            '/api/v1/equipment/assignments',
            headers=ew_headers,
            json={'item_id': str(ew_item.id), 'assigned_to_name': 'Brak webhooka'},
        )

        after_count = db_session.scalar(select(func.count(WebhookDeliveryLog.id)))
        assert after_count == before_count


# ---------------------------------------------------------------------------
# Tests: checkin → delivery log created
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCheckinWebhookDispatch:
    """Returning an asset fires equipment.checkin to matching endpoints."""

    def _checkout(
        self, client: TestClient, headers: dict[str, str], item_id: str
    ) -> str:
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={'item_id': item_id, 'assigned_to_name': 'Marek'},
        )
        r.raise_for_status()
        return cast(str, r.json()['id'])

    def test_checkin_creates_delivery_log(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        ew_user: User,
        checkin_webhook: WebhookEndpoint,
        db_session: Session,
    ) -> None:
        """After checkin, a delivery log with event_type=equipment.checkin exists."""
        assignment_id = self._checkout(client, ew_headers, str(ew_item.id))

        response = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=ew_headers,
            json={'checkin_condition': 'GOOD', 'checkin_notes': 'All OK'},
        )
        assert response.status_code == status.HTTP_200_OK

        payload = TenantEventPayload(
            organization_id=str(ew_item.organization_id),
            assignment_id=assignment_id,
            item_id=str(ew_item.id),
            item_name=ew_item.name,
            assigned_to_name='Marek',
            checkin_condition='GOOD',
            new_status='AVAILABLE',
            user_id=str(ew_user.id),
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            _run_dispatch(EquipmentEvent.CHECKIN, payload)

        logs = list(
            db_session.scalars(
                select(WebhookDeliveryLog).where(
                    WebhookDeliveryLog.webhook_endpoint_id == checkin_webhook.id,
                    WebhookDeliveryLog.event_type == 'equipment.checkin',
                )
            ).all()
        )
        assert len(logs) == 1

    def test_checkin_payload_contains_condition(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        ew_user: User,
        checkin_webhook: WebhookEndpoint,
        db_session: Session,
    ) -> None:
        """Payload has checkin_condition and new_status fields."""
        assignment_id = self._checkout(client, ew_headers, str(ew_item.id))
        response = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=ew_headers,
            json={'checkin_condition': 'DAMAGED'},
        )
        assert response.status_code == status.HTTP_200_OK

        payload = TenantEventPayload(
            organization_id=str(ew_item.organization_id),
            assignment_id=assignment_id,
            item_id=str(ew_item.id),
            item_name=ew_item.name,
            assigned_to_name='Marek',
            checkin_condition='DAMAGED',
            new_status='MAINTENANCE',
            user_id=str(ew_user.id),
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            _run_dispatch(EquipmentEvent.CHECKIN, payload)

        log = db_session.scalars(
            select(WebhookDeliveryLog).where(
                WebhookDeliveryLog.webhook_endpoint_id == checkin_webhook.id
            )
        ).first()
        assert log is not None
        payload_data = log.payload_json.get('data', {})
        assert payload_data.get('checkin_condition') == 'DAMAGED'
        assert payload_data.get('new_status') == 'MAINTENANCE'


# ---------------------------------------------------------------------------
# Tests: tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEquipmentWebhookTenantIsolation:
    """Org B webhook must NOT receive Org A's equipment events."""

    def test_other_org_webhook_not_triggered(
        self,
        client: TestClient,
        ew_headers: dict[str, str],
        ew_item: Item,
        db_session: Session,
    ) -> None:
        """A webhook belonging to a different org is not called."""
        other_org = Organization(
            name='Other Org',
            enabled_modules=['webhooks'],
        )
        db_session.add(other_org)
        db_session.commit()

        other_ep = WebhookEndpoint(
            organization_id=other_org.id,
            name='Other Org Hook',
            url='https://other.example.com/hook',
            http_method='POST',
            event_types=['equipment.checkout'],
            max_retries=0,
            timeout_seconds=5,
            is_active=True,
        )
        db_session.add(other_ep)
        db_session.commit()

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch('httpx.AsyncClient') as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            client.post(
                '/api/v1/equipment/assignments',
                headers=ew_headers,
                json={'item_id': str(ew_item.id), 'assigned_to_name': 'Tenant Test'},
            )

        other_logs = list(
            db_session.scalars(
                select(WebhookDeliveryLog).where(
                    WebhookDeliveryLog.webhook_endpoint_id == other_ep.id
                )
            ).all()
        )
        assert len(other_logs) == 0
