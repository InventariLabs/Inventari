"""Integration tests for the Webhooks module API.

Tests cover:
- CRUD for webhook endpoints
- Permission enforcement (admin-only for create/update/delete)
- Tenant isolation (org A cannot see org B's webhooks)
- Test ping endpoint
- Reactivation after circuit-breaker
- Delivery log listing
"""

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.services.token_service import create_access_token, get_password_hash


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org_with_webhooks(db_session: Session) -> Organization:
    """Organization with the webhooks module enabled."""
    org = Organization(
        name='Webhooks Org',
        enabled_modules=['webhooks'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def admin_user(db_session: Session, org_with_webhooks: Organization) -> User:
    from app.services.token_service import get_password_hash

    user = User(
        email='webhook_admin@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='Webhook Admin',
        organization_id=org_with_webhooks.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def member_user(db_session: Session, org_with_webhooks: Organization) -> User:
    from app.services.token_service import get_password_hash

    user = User(
        email='webhook_member@example.com',
        hashed_password=get_password_hash('memberpass'),
        full_name='Webhook Member',
        organization_id=org_with_webhooks.id,
        role='user',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(data={'sub': str(admin_user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def member_headers(member_user: User) -> dict[str, str]:
    token = create_access_token(data={'sub': str(member_user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def webhook_endpoint(
    db_session: Session, org_with_webhooks: Organization
) -> WebhookEndpoint:
    """A pre-created active webhook endpoint."""
    ep = WebhookEndpoint(
        organization_id=org_with_webhooks.id,
        name='Test Webhook',
        url='https://example.com/hook',
        http_method='POST',
        event_types=['item.used', 'item.created'],
        max_retries=3,
        retry_backoff_seconds=10,
        timeout_seconds=10,
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()
    db_session.refresh(ep)
    return ep


@pytest.fixture
def circuit_broken_webhook(
    db_session: Session, org_with_webhooks: Organization
) -> WebhookEndpoint:
    """A webhook that was auto-disabled by the circuit breaker."""
    ep = WebhookEndpoint(
        organization_id=org_with_webhooks.id,
        name='Broken Webhook',
        url='https://broken.example.com/hook',
        http_method='POST',
        event_types=['item.created'],
        max_retries=3,
        retry_backoff_seconds=10,
        timeout_seconds=10,
        is_active=False,
        consecutive_failures=10,
    )
    db_session.add(ep)
    db_session.commit()
    db_session.refresh(ep)
    return ep


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/webhooks/events
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAvailableEvents:
    def test_lists_events_for_authenticated_user(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/webhooks/events', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        events = response.json()
        assert isinstance(events, list)
        assert len(events) > 0
        event_types = [e['event_type'] for e in events]
        assert 'item.used' in event_types
        assert 'item.created' in event_types
        # The neutral-vocabulary aliases were removed; the
        # catalog must not offer a name nothing emits any more.
        assert 'item.consumed' not in event_types
        assert 'item.discarded' not in event_types

    def test_every_event_has_a_description(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """A missing description used to fall back to the technical name.

        Seventeen of forty-two rendered as `purchase_order.confirmed` and the
        like — a catalog that names itself explains nothing. The gap is caught
        here rather than on screen.
        """
        response = client.get('/api/v1/webhooks/events', headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        nameless = [
            event['event_type']
            for event in response.json()
            if event['description'] == event['event_type']
        ]
        assert nameless == []

    def test_events_of_a_disabled_module_are_marked_not_hidden(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Subscribing before switching a module on is a real case.

        So the catalog keeps such events and says they need a module, instead
        of offering `equipment.checkin` as if this organization could ever
        emit it.
        """
        response = client.get('/api/v1/webhooks/events', headers=admin_headers)
        events = {e['event_type']: e for e in response.json()}

        assert events['equipment.checkin']['source_module'] == 'equipment'
        assert events['purchase_order.confirmed']['source_module'] == (
            'purchase_orders'
        )
        # Core events belong to no module and are always emittable.
        assert events['item.created']['source_module'] is None
        assert events['item.created']['available'] is True
        # The equipment module is not enabled in this fixture's organization.
        assert events['equipment.checkin']['available'] is False

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.get('/api/v1/webhooks/events')
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_catalog_covers_module_events_not_only_the_core_enum(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Events a module registers must be offerable, not just `SystemEvent`.

        The catalog used to iterate `SystemEvent`, so anything a module declared
        in the payload registry — every `recipe.*` event — stayed invisible in
        the UI even once the API started accepting it.
        """
        response = client.get('/api/v1/webhooks/events', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        event_types = {e['event_type'] for e in response.json()}

        assert 'recipe.created' in event_types
        # The core enum must not regress out of the catalog.
        assert 'item.created' in event_types

    def test_catalog_has_no_duplicates(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Names live in both the registry and the enum — the union must dedupe."""
        response = client.get('/api/v1/webhooks/events', headers=admin_headers)
        event_types = [e['event_type'] for e in response.json()]

        assert len(event_types) == len(set(event_types))


# ---------------------------------------------------------------------------
# Tests: GET/POST /api/v1/webhooks/endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListEndpoints:
    def test_returns_empty_list_initially(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_lists_webhooks_for_org(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) == 1
        assert data[0]['name'] == 'Test Webhook'

    def test_member_cannot_list(
        self, client: TestClient, member_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        """A target URL is a credential at most receivers, so reading is admin work.

        This assertion used to say the opposite, and passed: the five mutating
        endpoints each carried the admin guard and the reads carried none.
        """
        response = client.get('/api/v1/webhooks/endpoints', headers=member_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.integration
class TestEventsAllModuleDisabled:
    """An endpoint whose events all belong to disabled modules can never fire.

    The fixture organization enables only ``webhooks`` — every event-source
    module (equipment, recipes, …) is off, which is exactly the silent state:
    ``is_active`` reads true, no delivery ever fails, and nothing says the
    subscriptions will never fire.
    """

    def _create(
        self, client: TestClient, headers: dict[str, str], event_types: list[str]
    ) -> dict[str, Any]:
        payload = {
            'name': f'Hook {event_types[0]}',
            'url': 'https://example.com/api/webhook/silent',
            'event_types': event_types,
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_201_CREATED
        data: dict[str, Any] = response.json()
        return data

    def test_only_disabled_module_events_is_flagged(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        data = self._create(client, admin_headers, ['equipment.checkin'])
        assert data['events_all_module_disabled'] is True

    def test_a_core_event_keeps_it_live(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        data = self._create(client, admin_headers, ['item.created'])
        assert data['events_all_module_disabled'] is False

    def test_one_core_event_among_module_events_keeps_it_live(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        data = self._create(
            client, admin_headers, ['equipment.checkin', 'item.created']
        )
        assert data['events_all_module_disabled'] is False

    def test_the_list_carries_the_same_flag(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        self._create(client, admin_headers, ['equipment.checkin'])
        self._create(client, admin_headers, ['item.created'])
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        by_name = {ep['name']: ep for ep in response.json()['items']}
        assert by_name['Hook equipment.checkin']['events_all_module_disabled'] is True
        assert by_name['Hook item.created']['events_all_module_disabled'] is False

    def test_enabling_the_module_clears_the_flag(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        org_with_webhooks: Organization,
    ) -> None:
        """The flag follows the module switches, not the endpoint's rows.

        Turning the module back on makes the subscriptions fireable again, and
        the next read says so without anybody editing the endpoint.
        """
        data = self._create(client, admin_headers, ['equipment.checkin'])
        assert data['events_all_module_disabled'] is True
        endpoint_id = data['id']

        org_with_webhooks.enabled_modules = [
            *org_with_webhooks.enabled_modules,
            'equipment',
        ]
        db_session.add(org_with_webhooks)
        db_session.commit()

        response = client.get(
            f'/api/v1/webhooks/endpoints/{endpoint_id}', headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['events_all_module_disabled'] is False


@pytest.mark.integration
class TestEventsUnknown:
    """A subscription the catalogue no longer offers is said, not silent.

    Endpoints seeded before ``item.consumed``/``item.discarded`` were cut
    still hold those names in ``event_types``, and the rows are not migrated
    — only development and demo stores carry them, and those are reset.
    What must not happen is the death being invisible: a card that reads
    active while nothing the endpoint subscribes to can ever match. The flag
    is computed per response, like ``events_all_module_disabled``, so it
    follows the catalogue rather than the row.
    """

    def _seed_endpoint(
        self, db_session: Session, org: Organization, event_types: list[str]
    ) -> WebhookEndpoint:
        """Write the row the API's validator would refuse today."""
        endpoint = WebhookEndpoint(
            organization_id=org.id,
            name='Legacy Hook',
            url='https://example.com/api/webhook/legacy',
            event_types=event_types,
        )
        db_session.add(endpoint)
        db_session.commit()
        db_session.refresh(endpoint)
        return endpoint

    def test_a_withdrawn_name_is_flagged(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        org_with_webhooks: Organization,
    ) -> None:
        self._seed_endpoint(db_session, org_with_webhooks, ['item.consumed'])
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        by_name = {ep['name']: ep for ep in response.json()['items']}
        assert by_name['Legacy Hook']['events_unknown'] is True

    def test_a_live_catalogue_entry_is_not_flagged(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        org_with_webhooks: Organization,
    ) -> None:
        self._seed_endpoint(db_session, org_with_webhooks, ['item.used'])
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        by_name = {ep['name']: ep for ep in response.json()['items']}
        assert by_name['Legacy Hook']['events_unknown'] is False

    def test_one_withdrawn_name_among_live_ones_still_flags(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        org_with_webhooks: Organization,
    ) -> None:
        """The flag names the dead subscription, not the endpoint's health:
        a live sibling keeps it firing for other events, and the card still
        owes the administrator the half that will never fire."""
        self._seed_endpoint(
            db_session, org_with_webhooks, ['item.used', 'item.consumed']
        )
        response = client.get('/api/v1/webhooks/endpoints', headers=admin_headers)
        by_name = {ep['name']: ep for ep in response.json()['items']}
        assert by_name['Legacy Hook']['events_unknown'] is True

    def test_the_single_endpoint_read_carries_it_too(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        org_with_webhooks: Organization,
    ) -> None:
        endpoint = self._seed_endpoint(
            db_session, org_with_webhooks, ['item.discarded']
        )
        response = client.get(
            f'/api/v1/webhooks/endpoints/{endpoint.id}', headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['events_unknown'] is True


@pytest.mark.integration
class TestCreateEndpoint:
    def test_accepts_a_module_registered_event(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """`recipe.created` is a real, emitted event — subscribing must work.

        The validator accepted only `SystemEvent` values, so every event a
        module contributes to the payload registry was rejected with 422 even
        though the bus emits it.
        """
        payload = {
            'name': 'Recipe Webhook',
            'url': 'https://example.com/api/webhook/recipes',
            'event_types': ['recipe.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['event_types'] == ['recipe.created']

    def test_rejects_an_unknown_event(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Widening to the registry must not turn the validator into a no-op."""
        payload = {
            'name': 'Nonsense Webhook',
            'url': 'https://example.com/api/webhook/nope',
            'event_types': ['definitely.not_an_event'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_admin_can_create(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'HA Webhook',
            'url': 'https://example.com/api/webhook/abc',
            'http_method': 'POST',
            'event_types': ['item.used'],
            'max_retries': 3,
            'timeout_seconds': 10,
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'HA Webhook'
        assert data['has_secret'] is False
        assert 'secret' not in data  # Never expose secret

    def test_member_cannot_create(
        self, client: TestClient, member_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Forbidden',
            'url': 'https://example.com/hook',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=member_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_member_with_admin_access_custom_role_can_create(
        self,
        client: TestClient,
        db_session: Session,
        org_with_webhooks: Organization,
        member_user: User,
    ) -> None:
        """A custom role carrying admin:access reaches the webhook mutations
               the built-in admin level reaches — the guard checks the permission,
        not the role name."""
        from app.models.role import Role, UserRole

        role = Role(
            organization_id=org_with_webhooks.id,
            name='Org Administrator',
            permissions=['admin:access'],
            is_system=False,
        )
        db_session.add(role)
        db_session.flush()
        db_session.add(UserRole(user_id=member_user.id, role_id=role.id))
        db_session.commit()

        payload = {
            'name': 'Custom Role Webhook',
            'url': 'https://example.com/hook',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=_auth(member_user)
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_member_is_refused_with_the_shared_admin_message(
        self, client: TestClient, member_headers: dict[str, str]
    ) -> None:
        """The guard is the core admin dependency, so the 403 carries its key."""
        payload = {
            'name': 'Forbidden',
            'url': 'https://example.com/hook',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=member_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()['detail'] == {
            'code': 'FORBIDDEN',
            'message': get_error_message('admin_permissions_required', 'en'),
        }

    def test_invalid_url_returns_422(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Bad URL',
            'url': 'not-a-url',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_private_address_says_why_and_how(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """A refusal the reader can act on: which address, and the way out.

               The guard has always rejected private targets, but the sentence it
               produced was an English literal built for logs — and the form dropped
        it entirely. The reason now travels as a code and comes back
               as a message in the request language, naming the host and the
               installation switch that allows local addresses.
        """
        payload = {
            'name': 'Home Assistant',
            'url': 'http://192.168.1.50:8123/api/webhook/x',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints',
            json=payload,
            headers={**admin_headers, 'Accept-Language': 'pl'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()['detail']
        # The field travels with the message, so the form can point at the URL
        # box instead of dropping a toast with nothing to aim at.
        assert detail['field'] == 'url'
        assert detail['code'] == 'WEBHOOK_URL_PRIVATE'
        assert '192.168.1.50' in detail['message']
        assert 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS' in detail['message']
        assert detail['message'] == get_error_message(
            'webhook_url_private', 'pl'
        ).format(host='192.168.1.50', resolved='')

    def test_loopback_hostname_says_why(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Local',
            'url': 'http://localhost:9000/hook',
            'event_types': ['item.created'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()['detail']['message'] == get_error_message(
            'webhook_url_loopback', 'en'
        ).format(host='localhost', resolved='')

    def test_unknown_event_type_returns_422(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Bad Events',
            'url': 'https://example.com/hook',
            'event_types': ['totally.unknown.event'],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_secret_is_stored_encrypted(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        await db.commit()  # commit user so API can authenticate
        headers = _auth(async_test_user)

        # Create org with webhooks module enabled
        org = Organization(
            name='Webhooks Test Org', enabled_modules=['webhooks', 'core']
        )
        db.add(org)
        await db.flush()
        # Update user to be in this org
        async_test_user.organization_id = org.id
        async_test_user.role = 'admin'
        await db.commit()

        payload = {
            'name': 'With Secret',
            'url': 'https://example.com/hook',
            'event_types': ['item.created'],
            'secret': 'mysupersecret',
        }
        response = await real_async_client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=headers
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['has_secret'] is True

        result = await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.id == data['id'])
        )
        ep = result.scalars().first()
        assert ep is not None
        assert ep.secret is not None
        assert ep.secret.startswith('enc:')

    def test_empty_event_types_returns_422(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'No Events',
            'url': 'https://example.com/hook',
            'event_types': [],
        }
        response = client.post(
            '/api/v1/webhooks/endpoints', json=payload, headers=admin_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ---------------------------------------------------------------------------
# Tests: GET/PUT/DELETE single endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetEndpoint:
    def test_get_existing(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.get(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['id'] == str(webhook_endpoint.id)

    def test_get_not_found(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.get(
            f'/api/v1/webhooks/endpoints/{uuid4()}',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_tenant_isolation(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """Org B user cannot access Org A's webhook."""
        db = real_async_db_session
        await db.commit()  # commit user
        headers = _auth(async_test_user)

        # Create webhook endpoint for async_test_user's org
        # First need to ensure webhooks module is enabled for the org
        async_test_household = await db.get(
            Organization, async_test_user.organization_id
        )
        assert async_test_household is not None
        async_test_household.enabled_modules = ['webhooks', 'core']
        await db.commit()

        create_resp = await real_async_client.post(
            '/api/v1/webhooks/endpoints',
            json={
                'name': 'Test Webhook',
                'url': 'https://example.com/hook',
                'http_method': 'POST',
                'event_types': ['item.used'],
            },
            headers=headers,
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        webhook_id = create_resp.json()['id']

        # Create other org + user
        other_org = Organization(name='Other Org', enabled_modules=['webhooks', 'core'])
        db.add(other_org)
        await db.flush()

        other_user = User(
            email=f'other_{uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('pass'),
            full_name='Other',
            organization_id=other_org.id,
            role='admin',
            is_active=True,
        )
        db.add(other_user)
        await db.commit()

        other_headers = _auth(other_user)

        response = await real_async_client.get(
            f'/api/v1/webhooks/endpoints/{webhook_id}',
            headers=other_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestUpdateEndpoint:
    def test_admin_can_update_name(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.put(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}',
            json={'name': 'Updated Name'},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Updated Name'

    def test_masked_secret_does_not_change_secret(
        self, client: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        from sqlalchemy import select

        # Create endpoint with secret
        create_response = client.post(
            '/api/v1/webhooks/endpoints',
            json={
                'name': 'Sec',
                'url': 'https://example.com/h',
                'event_types': ['item.created'],
                'secret': 'original_secret',
            },
            headers=admin_headers,
        )
        ep_id = create_response.json()['id']
        ep_orm = (
            db_session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
            )
            .scalars()
            .first()
        )
        assert ep_orm is not None
        original_secret = ep_orm.secret

        # Update with masked value — should not change secret
        client.put(
            f'/api/v1/webhooks/endpoints/{ep_id}',
            json={'secret': '**********'},
            headers=admin_headers,
        )
        db_session.expire_all()
        ep_orm_after = (
            db_session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
            )
            .scalars()
            .first()
        )
        assert ep_orm_after is not None
        current_secret = ep_orm_after.secret
        assert current_secret == original_secret

    def test_member_cannot_update(
        self, client: TestClient, member_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.put(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}',
            json={'name': 'Hacked'},
            headers=member_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.integration
class TestDeleteEndpoint:
    def test_admin_can_delete(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        webhook_endpoint: Any,
        db_session: Session,
    ) -> None:
        endpoint_id = webhook_endpoint.id
        response = client.delete(
            f'/api/v1/webhooks/endpoints/{endpoint_id}',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        from sqlalchemy import select

        ep = (
            db_session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id)
            )
            .scalars()
            .first()
        )
        assert ep is None

    def test_member_cannot_delete(
        self, client: TestClient, member_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.delete(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}',
            headers=member_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Tests: POST /reactivate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReactivateEndpoint:
    def test_admin_can_reactivate(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        circuit_broken_webhook: Any,
        db_session: Session,
    ) -> None:
        response = client.post(
            f'/api/v1/webhooks/endpoints/{circuit_broken_webhook.id}/reactivate',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['is_active'] is True
        assert data['consecutive_failures'] == 0

    def test_member_cannot_reactivate(
        self,
        client: TestClient,
        member_headers: dict[str, str],
        circuit_broken_webhook: Any,
    ) -> None:
        response = client.post(
            f'/api/v1/webhooks/endpoints/{circuit_broken_webhook.id}/reactivate',
            headers=member_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Tests: POST /test
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTestEndpoint:
    def test_sends_test_ping_success(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = 'OK'

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_client_cls:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client_instance

            response = client.post(
                f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/test',
                headers=admin_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['success'] is True
        assert data['status_code'] == 200
        assert 'delivery_id' in data

    def test_test_ping_failure_returns_error(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_client_cls:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            import httpx

            mock_client_instance.request = AsyncMock(
                side_effect=httpx.ConnectError('Connection refused')
            )
            mock_client_cls.return_value = mock_client_instance

            response = client.post(
                f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/test',
                headers=admin_headers,
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['success'] is False
        assert data['error'] is not None

    def test_a_refusal_reports_the_status_not_the_receivers_page(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        """A 405 from a web server is a page of HTML; the toast is not its home."""
        page = '<!doctype html><html><head><title>Example Domain</title></head></html>'
        mock_response = AsyncMock()
        mock_response.status_code = 405
        mock_response.text = page

        with patch(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient'
        ) as mock_client_cls:
            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client_instance

            response = client.post(
                f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/test',
                headers=admin_headers,
            )

        data = response.json()
        assert data['success'] is False
        assert data['status_code'] == 405
        assert data['error'] == 'The receiver answered 405 Method Not Allowed'

        # The body is still on record, where an operator reads it on purpose.
        deliveries = client.get(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/deliveries',
            headers=admin_headers,
        ).json()['items']
        assert [d['status_code'] for d in deliveries] == [405]
        assert page in (deliveries[0].get('error_message') or '')

    def test_member_cannot_test(
        self, client: TestClient, member_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.post(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/test',
            headers=member_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Tests: GET /deliveries
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeliveryLogs:
    def test_empty_deliveries_initially(
        self, client: TestClient, admin_headers: dict[str, str], webhook_endpoint: Any
    ) -> None:
        response = client.get(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/deliveries',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_lists_delivery_logs(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        webhook_endpoint: Any,
        db_session: Session,
    ) -> None:
        log = WebhookDeliveryLog(
            webhook_endpoint_id=webhook_endpoint.id,
            organization_id=webhook_endpoint.organization_id,
            event_type='item.used',
            payload_json={'event': 'item.used'},
            status_code=200,
            attempt_number=1,
            delivery_status='success',
        )
        db_session.add(log)
        db_session.commit()

        response = client.get(
            f'/api/v1/webhooks/endpoints/{webhook_endpoint.id}/deliveries',
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        logs = response.json()['items']
        assert len(logs) == 1
        assert logs[0]['event_type'] == 'item.used'
        assert logs[0]['status_code'] == 200
