"""Integration tests for webhook_crud_service (async functions).

Covers: _org_uuid, get_webhook_or_404, to_response, list_endpoints,
create_endpoint, update_endpoint, delete_endpoint, reactivate_endpoint,
list_deliveries.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.organization import Organization
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.schemas import WebhookEndpointResponse
from app.modules.webhooks.webhook_crud_service import (
    _org_uuid,
    create_endpoint_async,
    delete_endpoint_async,
    get_webhook_or_404_async,
    list_deliveries_async,
    list_endpoints_async,
    reactivate_endpoint_async,
    to_response,
    update_endpoint_async,
)


@pytest.mark.integration
class TestOrgUuid:
    def test_converts_string_to_uuid(self) -> None:
        uid = uuid4()
        result = _org_uuid(str(uid))
        assert isinstance(result, UUID)
        assert result == uid

    def test_passes_through_uuid(self) -> None:
        uid = uuid4()
        result = _org_uuid(uid)
        assert result is uid

    def test_raises_on_invalid_string(self) -> None:
        with pytest.raises(ValueError):
            _org_uuid('not-a-uuid')


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetWebhookOr404:
    async def test_returns_existing_endpoint(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Find Me',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = await get_webhook_or_404_async(
            ep.id, async_test_household.id, real_async_db_session
        )
        assert result.id == ep.id
        assert result.name == 'Find Me'

    async def test_raises_not_found_for_missing_id(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        with pytest.raises(NotFoundException):
            await get_webhook_or_404_async(
                uuid4(), async_test_household.id, real_async_db_session
            )

    async def test_raises_not_found_for_wrong_org(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Wrong Org',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        other_org_id = uuid4()
        with pytest.raises(NotFoundException):
            await get_webhook_or_404_async(ep.id, other_org_id, real_async_db_session)

    async def test_accepts_string_org_id(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='String Org',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = await get_webhook_or_404_async(
            ep.id, str(async_test_household.id), real_async_db_session
        )
        assert result.id == ep.id


@pytest.mark.integration
@pytest.mark.asyncio
class TestToResponse:
    async def test_converts_model_to_schema(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Convert Me',
            url='https://example.com/hook',
            secret='enc:some_encrypted_value',
            http_method='PUT',
            event_types=['item.used'],
            max_retries=5,
            retry_backoff_seconds=20,
            timeout_seconds=15,
            is_active=True,
            consecutive_failures=2,
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = to_response(ep)
        assert isinstance(result, WebhookEndpointResponse)
        assert result.id == ep.id
        assert result.name == 'Convert Me'
        assert result.url == 'https://example.com/hook'
        assert result.has_secret is True
        assert result.http_method == 'PUT'
        assert result.event_types == ['item.used']
        assert result.max_retries == 5
        assert result.retry_backoff_seconds == 20
        assert result.timeout_seconds == 15
        assert result.is_active is True
        assert result.consecutive_failures == 2

    async def test_has_secret_false_when_no_secret(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='No Secret',
            url='https://example.com/hook',
            secret=None,
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = to_response(ep)
        assert result.has_secret is False

    async def test_empty_event_types_default_to_empty_list(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='No Events',
            url='https://example.com/hook',
            http_method='POST',
            event_types=None,
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = to_response(ep)
        assert result.event_types == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestListEndpoints:
    async def test_returns_empty_list_initially(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        result = await list_endpoints_async(
            async_test_household.id, real_async_db_session
        )
        assert result == []

    async def test_returns_endpoints_for_org(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        for i in range(3):
            ep = WebhookEndpoint(
                organization_id=async_test_household.id,
                name=f'Hook {i}',
                url=f'https://example.com/hook{i}',
                http_method='POST',
                event_types=['item.created'],
            )
            real_async_db_session.add(ep)
        await real_async_db_session.commit()

        result = await list_endpoints_async(
            async_test_household.id, real_async_db_session
        )
        assert len(result) == 3

    async def test_does_not_return_other_org_endpoints(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='My Hook',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()

        other_org_id = uuid4()
        result = await list_endpoints_async(other_org_id, real_async_db_session)
        assert result == []

    async def test_accepts_string_org_id(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='String Org',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()

        result = await list_endpoints_async(
            str(async_test_household.id), real_async_db_session
        )
        assert len(result) == 1

    async def test_ordered_by_created_at_desc(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        now = datetime.now(UTC)
        names = ['First', 'Second', 'Third']
        for i, name in enumerate(names):
            ep = WebhookEndpoint(
                organization_id=async_test_household.id,
                name=name,
                url=f'https://example.com/{name.lower()}',
                http_method='POST',
                event_types=['item.created'],
                created_at=now + timedelta(minutes=i),
            )
            real_async_db_session.add(ep)
        await real_async_db_session.commit()

        result = await list_endpoints_async(
            async_test_household.id, real_async_db_session
        )
        assert result[0].name == 'Third'
        assert result[-1].name == 'First'


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateEndpoint:
    async def test_creates_endpoint_with_all_fields(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        result = await create_endpoint_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            name='Full Webhook',
            url='https://example.com/hook',
            secret='my_secret',
            http_method='PUT',
            event_types=['item.created', 'item.used'],
            max_retries=5,
            retry_backoff_seconds=30,
            timeout_seconds=20,
            is_active=False,
        )
        assert result.id is not None
        assert result.name == 'Full Webhook'
        assert result.url == 'https://example.com/hook'
        assert result.secret == 'my_secret'
        assert result.http_method == 'PUT'
        assert set(result.event_types) == {'item.created', 'item.used'}
        assert result.max_retries == 5
        assert result.retry_backoff_seconds == 30
        assert result.timeout_seconds == 20
        assert result.is_active is False
        assert result.organization_id == async_test_household.id

    async def test_creates_endpoint_with_string_org_id(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        result = await create_endpoint_async(
            real_async_db_session,
            organization_id=str(async_test_household.id),
            name='String Org',
            url='https://example.com/hook',
            secret=None,
            http_method='POST',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
        )
        assert result.organization_id == async_test_household.id

    async def test_endpoint_persisted_in_db(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        result = await create_endpoint_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            name='Persisted',
            url='https://example.com/hook',
            secret=None,
            http_method='POST',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
        )
        ep_id = result.id

        loaded = (
            (
                await real_async_db_session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.name == 'Persisted'


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateEndpoint:
    async def _make_endpoint(self, db: AsyncSession, org_id: UUID) -> WebhookEndpoint:
        ep = WebhookEndpoint(
            organization_id=org_id,
            name='Original',
            url='https://original.example.com/hook',
            secret='original_secret',
            http_method='POST',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
            consecutive_failures=5,
        )
        db.add(ep)
        await db.commit()
        await db.refresh(ep)
        return ep

    async def test_updates_only_specified_fields(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)

        result = await update_endpoint_async(
            real_async_db_session, ep, name='Updated Name'
        )

        assert result.name == 'Updated Name'
        assert result.url == 'https://original.example.com/hook'
        assert result.secret == 'original_secret'
        assert result.http_method == 'POST'
        assert result.event_types == ['item.created']
        assert result.max_retries == 3
        assert result.is_active is True

    async def test_updates_multiple_fields(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)

        result = await update_endpoint_async(
            real_async_db_session,
            ep,
            name='New Name',
            url='https://new.example.com/hook',
            http_method='PUT',
            max_retries=7,
        )

        assert result.name == 'New Name'
        assert result.url == 'https://new.example.com/hook'
        assert result.http_method == 'PUT'
        assert result.max_retries == 7
        assert result.retry_backoff_seconds == 10

    async def test_none_values_do_not_overwrite(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)

        result = await update_endpoint_async(real_async_db_session, ep)

        assert result.name == 'Original'
        assert result.url == 'https://original.example.com/hook'
        assert result.secret == 'original_secret'

    async def test_can_deactivate(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)

        result = await update_endpoint_async(real_async_db_session, ep, is_active=False)
        assert result.is_active is False

    async def test_can_update_event_types(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)

        result = await update_endpoint_async(
            real_async_db_session, ep, event_types=['item.used', 'item.disposed']
        )
        assert set(result.event_types) == {'item.used', 'item.disposed'}

    async def test_persists_changes(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._make_endpoint(real_async_db_session, async_test_household.id)
        ep_id = ep.id
        await update_endpoint_async(real_async_db_session, ep, name='Persisted Update')

        loaded = (
            (
                await real_async_db_session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.name == 'Persisted Update'


@pytest.mark.integration
@pytest.mark.asyncio
class TestDeleteEndpoint:
    async def test_deletes_endpoint(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Delete Me',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)
        ep_id = ep.id

        await delete_endpoint_async(real_async_db_session, ep)

        loaded = (
            (
                await real_async_db_session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is None

    async def test_cascade_deletes_delivery_logs(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='With Logs',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        log = WebhookDeliveryLog(
            webhook_endpoint_id=ep.id,
            organization_id=async_test_household.id,
            event_type='item.created',
            payload_json={'test': True},
            status_code=200,
            delivery_status='success',
        )
        real_async_db_session.add(log)
        await real_async_db_session.commit()

        await delete_endpoint_async(real_async_db_session, ep)

        remaining = (
            (
                await real_async_db_session.execute(
                    select(WebhookDeliveryLog).where(
                        WebhookDeliveryLog.webhook_endpoint_id == ep.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestReactivateEndpoint:
    async def test_reactivates_and_resets_failures(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Broken',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
            is_active=False,
            consecutive_failures=15,
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = await reactivate_endpoint_async(real_async_db_session, ep)

        assert result.is_active is True
        assert result.consecutive_failures == 0

    async def test_persists_state(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Broken Persist',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
            is_active=False,
            consecutive_failures=8,
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)
        ep_id = ep.id

        await reactivate_endpoint_async(real_async_db_session, ep)

        loaded = (
            (
                await real_async_db_session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == ep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.is_active is True
        assert loaded.consecutive_failures == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestListDeliveries:
    async def test_returns_empty_when_no_logs(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='No Logs',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        result = await list_deliveries_async(
            real_async_db_session, ep.id, async_test_household.id, limit=10
        )
        assert list(result) == []

    async def test_returns_delivery_logs(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='With Logs',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        for i in range(3):
            log = WebhookDeliveryLog(
                webhook_endpoint_id=ep.id,
                organization_id=async_test_household.id,
                event_type='item.created',
                payload_json={'idx': i},
                status_code=200,
                delivery_status='success',
            )
            real_async_db_session.add(log)
        await real_async_db_session.commit()

        result = await list_deliveries_async(
            real_async_db_session, ep.id, async_test_household.id, limit=10
        )
        logs = list(result)
        assert len(logs) == 3

    async def test_cursor_pagination(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Paginated',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        now = datetime.now(UTC)
        logs = []
        for i in range(5):
            log = WebhookDeliveryLog(
                webhook_endpoint_id=ep.id,
                organization_id=async_test_household.id,
                event_type='item.created',
                payload_json={'idx': i},
                status_code=200,
                delivery_status='success',
                created_at=now - timedelta(minutes=i),
            )
            real_async_db_session.add(log)
            logs.append(log)
        await real_async_db_session.commit()

        first_page = list(
            await list_deliveries_async(
                real_async_db_session, ep.id, async_test_household.id, limit=2
            )
        )
        assert len(first_page) == 3  # limit + 1 for has_more detection

        cursor = first_page[-1].created_at
        second_page = list(
            await list_deliveries_async(
                real_async_db_session,
                ep.id,
                async_test_household.id,
                limit=2,
                cursor_ts=cursor,
            )
        )
        assert len(second_page) > 0

        all_ids = {log.id for log in first_page} | {log.id for log in second_page}
        assert len(all_ids) == 5

    async def test_does_not_return_other_endpoint_logs(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep1 = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='EP1',
            url='https://example.com/hook1',
            http_method='POST',
            event_types=['item.created'],
        )
        ep2 = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='EP2',
            url='https://example.com/hook2',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add_all([ep1, ep2])
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep1)
        await real_async_db_session.refresh(ep2)

        log = WebhookDeliveryLog(
            webhook_endpoint_id=ep1.id,
            organization_id=async_test_household.id,
            event_type='item.created',
            payload_json={'test': True},
            status_code=200,
            delivery_status='success',
        )
        real_async_db_session.add(log)
        await real_async_db_session.commit()

        result = await list_deliveries_async(
            real_async_db_session, ep2.id, async_test_household.id, limit=10
        )
        assert list(result) == []

    async def test_ordered_by_created_at_desc(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = WebhookEndpoint(
            organization_id=async_test_household.id,
            name='Ordered',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
        )
        real_async_db_session.add(ep)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(ep)

        now = datetime.now(UTC)
        for i in range(3):
            log = WebhookDeliveryLog(
                webhook_endpoint_id=ep.id,
                organization_id=async_test_household.id,
                event_type='item.created',
                payload_json={'idx': i},
                status_code=200,
                delivery_status='success',
                created_at=now - timedelta(minutes=i),
            )
            real_async_db_session.add(log)
        await real_async_db_session.commit()

        result = await list_deliveries_async(
            real_async_db_session, ep.id, async_test_household.id, limit=10
        )
        logs = list(result)
        assert logs[0].created_at >= logs[1].created_at >= logs[2].created_at


@pytest.mark.integration
@pytest.mark.asyncio
class TestAutoDisabledTrace:
    """Why an endpoint is off, kept apart from the fact that it is.

    ``is_active = false`` had two causes and one appearance, and the card
    named the second one for both — an endpoint paused for maintenance wore
    the circuit breaker's badge, sending its owner to look for failed
    deliveries that had never happened.
    """

    async def _endpoint(
        self, db: AsyncSession, org_id: UUID, **kwargs: object
    ) -> WebhookEndpoint:
        ep = WebhookEndpoint(
            organization_id=org_id,
            name='Trace',
            url='https://example.com/hook',
            http_method='POST',
            event_types=['item.created'],
            **kwargs,
        )
        db.add(ep)
        await db.commit()
        await db.refresh(ep)
        return ep

    async def test_endpoint_paused_by_hand_carries_no_breaker_trace(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._endpoint(
            real_async_db_session, async_test_household.id, is_active=False
        )

        result = to_response(ep)

        assert result.is_active is False
        assert result.auto_disabled_at is None

    async def test_switching_it_off_by_hand_clears_an_earlier_breaker_trace(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        # Reactivated after a trip, then paused by a person: the breaker is no
        # longer the reason, so its trace must not outlive the decision.
        ep = await self._endpoint(
            real_async_db_session,
            async_test_household.id,
            is_active=True,
            auto_disabled_at=datetime.now(UTC),
        )

        result = await update_endpoint_async(real_async_db_session, ep, is_active=False)

        assert result.auto_disabled_at is None

    async def test_saving_the_form_on_a_cut_off_channel_keeps_the_trace(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        # The edit form always sends is_active. Sent unchanged on a channel the
        # breaker cut off, it is no decision, and the next failure would
        # journal and announce the same cut-off a second time.
        cut_off_at = datetime.now(UTC)
        ep = await self._endpoint(
            real_async_db_session,
            async_test_household.id,
            is_active=False,
            consecutive_failures=4,
            auto_disabled_at=cut_off_at,
        )

        result = await update_endpoint_async(
            real_async_db_session, ep, name='Renamed', is_active=False
        )

        assert result.is_active is False
        assert result.auto_disabled_at == cut_off_at

    async def test_reactivating_clears_the_trace(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        ep = await self._endpoint(
            real_async_db_session,
            async_test_household.id,
            is_active=False,
            consecutive_failures=15,
            auto_disabled_at=datetime.now(UTC),
        )

        result = await reactivate_endpoint_async(real_async_db_session, ep)

        assert result.is_active is True
        assert result.auto_disabled_at is None

    async def test_a_new_target_url_ends_the_old_verdict(
        self, real_async_db_session: AsyncSession, async_test_household: Organization
    ) -> None:
        # The failures were about the old address; the reset of the counter
        # already said so, and the trace has to travel with it.
        ep = await self._endpoint(
            real_async_db_session,
            async_test_household.id,
            is_active=False,
            consecutive_failures=12,
            auto_disabled_at=datetime.now(UTC),
        )

        result = await update_endpoint_async(
            real_async_db_session, ep, url='https://elsewhere.example.com/hook'
        )

        assert result.consecutive_failures == 0
        assert result.auto_disabled_at is None
