"""Switching an integration module off has to take away what it does, not the panel.

`require_module` guarded the routers of both modules and nothing else. What
each module does without a person present — resolving a key at authentication
time, matching an event to endpoints, retrying a failed delivery — never asked
whether the organization still had it, so switching it off left the behaviour
running and removed the only controls for stopping it: the admin could no
longer see the key or the endpoint, could not revoke either, and nothing said
that the way back was to switch the module on again.

Both purpose cards already promised the other thing. `api_keys`: "Existing keys
stop working." `webhooks`: "the outside world simply stops hearing."
"""

from uuid import UUID, uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.services.token_service import create_access_token, get_password_hash


def _org(db_session: Session, *modules: str) -> Organization:
    org = Organization(name=f'Org {uuid4().hex[:6]}', enabled_modules=list(modules))
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def _admin(db_session: Session, org: Organization) -> User:
    user = User(
        email=f'switch_admin_{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='Switch Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _switch_off(db_session: Session, org: Organization, module: str) -> None:
    """What the module store's toggle does, as far as this table is concerned."""
    org.enabled_modules = [m for m in (org.enabled_modules or []) if m != module]
    db_session.add(org)
    db_session.commit()


@pytest.mark.integration
class TestApiKeyStopsAuthenticating:
    def test_a_valid_key_answers_401_once_the_module_is_off(
        self, client: TestClient, db_session: Session
    ) -> None:
        org = _org(db_session, 'core', 'items', 'api_keys')
        admin = _admin(db_session, org)
        admin_headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(admin.id)})}'
        }

        created = client.post(
            '/api/v1/api-keys',
            json={'name': 'Automation'},
            headers=admin_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED
        raw_key = created.json()['raw_key']
        key_headers = {'Authorization': f'Bearer {raw_key}'}

        # The key works while the module is on — otherwise the assertion below
        # would pass for the wrong reason.
        assert client.get('/api/v1/items', headers=key_headers).status_code == (
            status.HTTP_200_OK
        )

        _switch_off(db_session, org, 'api_keys')

        refused = client.get('/api/v1/items', headers=key_headers)
        assert refused.status_code == status.HTTP_401_UNAUTHORIZED

    def test_writing_with_the_key_is_refused_too(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Reading was the measured case; writing is the one that costs.

        The report saw `POST /items` create a row with the module off.
        """
        org = _org(db_session, 'core', 'items', 'api_keys')
        admin = _admin(db_session, org)
        admin_headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(admin.id)})}'
        }
        raw_key = client.post(
            '/api/v1/api-keys', json={'name': 'Writer'}, headers=admin_headers
        ).json()['raw_key']

        _switch_off(db_session, org, 'api_keys')

        refused = client.post(
            '/api/v1/items',
            json={'name': 'Smuggled in', 'quantity': 1},
            headers={'Authorization': f'Bearer {raw_key}'},
        )
        assert refused.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestWebhookStopsSending:
    async def _dispatch(self, org_id: UUID) -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from sqlalchemy.pool import NullPool

        from app import database as app_database
        from app.config import settings
        from app.core.contracts.events import ItemCreatedPayload
        from app.core.events import SystemEvent
        from app.modules.webhooks.webhook_service import dispatch_event

        # The subscriber opens its own sessions; this test never
        # started the app, so the global factory is None — hand it a throwaway
        # NullPool factory over the test database for this one call.
        async_url = settings.DATABASE_URL.replace(
            'postgresql://', 'postgresql+asyncpg://', 1
        )
        engine = create_async_engine(async_url, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        original = app_database.AsyncSessionLocal
        app_database.AsyncSessionLocal = factory
        try:
            await dispatch_event(
                SystemEvent.ITEM_CREATED,
                ItemCreatedPayload(organization_id=str(org_id)),
            )
        finally:
            app_database.AsyncSessionLocal = original
            await engine.dispose()

    def _endpoint(self, db_session: Session, org: Organization) -> WebhookEndpoint:
        ep = WebhookEndpoint(
            organization_id=org.id,
            name='Listener',
            url='https://example.com/hook',
            event_types=['item.created'],
            is_active=True,
        )
        db_session.add(ep)
        db_session.commit()
        db_session.refresh(ep)
        return ep

    def _delivery_rows(self, db_session: Session, org: Organization) -> int:
        return (
            db_session.query(WebhookDeliveryLog)
            .filter(WebhookDeliveryLog.organization_id == org.id)
            .count()
        )

    @pytest.mark.asyncio
    async def test_no_delivery_row_when_the_module_is_off(
        self, db_session: Session
    ) -> None:
        org = _org(db_session, 'core', 'items', 'webhooks')
        self._endpoint(db_session, org)
        _switch_off(db_session, org, 'webhooks')

        await self._dispatch(UUID(str(org.id)))

        db_session.expire_all()
        assert self._delivery_rows(db_session, org) == 0
