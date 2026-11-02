"""A webhook endpoint is a channel organization data leaves by.

``grep audit_log backend/app/modules/webhooks/*.py`` used to return nothing.
Across a session that created four endpoints, deleted three, changed one and
had one cut off by the circuit breaker and restored by hand, the organization
journal held a single line — the module being switched on.

That matters more here than for an ordinary record: the endpoint carries an
HMAC signature the receiver may treat as proof of origin, and the delivery
history — the module's only other trace — is cascaded away with the endpoint
it belonged to. After the deletion there is nothing left to read.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookEndpoint
from app.services.token_service import create_access_token, get_password_hash

ENDPOINTS = '/api/v1/webhooks/endpoints'


@pytest.fixture
def trace_org(db_session: Session) -> Organization:
    org = Organization(name='Trace Org', enabled_modules=['webhooks'])
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def trace_admin(db_session: Session, trace_org: Organization) -> User:
    user = User(
        email='trace_admin@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='Trace Admin',
        organization_id=trace_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def trace_headers(trace_admin: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(trace_admin.id)})}'
    }


def _webhook_entries(
    client: TestClient, headers: dict[str, str]
) -> list[dict[str, Any]]:
    log = client.get('/api/v1/audit-log', headers=headers)
    assert log.status_code == status.HTTP_200_OK, log.text
    return [e for e in log.json()['items'] if e['target_type'] == 'webhook_endpoint']


@pytest.mark.integration
class TestTheChannelLeavesATrace:
    def test_create_change_delete_leave_three_entries(
        self,
        client: TestClient,
        trace_headers: dict[str, str],
    ) -> None:
        created = client.post(
            ENDPOINTS,
            json={
                'name': 'Partner ERP',
                'url': 'https://example.com/hook',
                'event_types': ['item.created'],
            },
            headers=trace_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        webhook_id = created.json()['id']

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={'url': 'https://example.com/hook-v2'},
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        deleted = client.delete(f'{ENDPOINTS}/{webhook_id}', headers=trace_headers)
        assert deleted.status_code == status.HTTP_204_NO_CONTENT

        entries = _webhook_entries(client, trace_headers)
        assert [e['action'] for e in entries] == ['HARD_DELETE', 'UPDATE', 'CREATE']
        assert all(e['target_id'] == webhook_id for e in entries)

        by_action = {e['action']: e for e in entries}
        assert by_action['CREATE']['snapshot']['url'] == 'https://example.com/hook'
        assert by_action['UPDATE']['snapshot']['url'] == 'https://example.com/hook-v2'
        # The row and its whole delivery history are gone; the name and the
        # destination survive here and nowhere else.
        assert by_action['HARD_DELETE']['snapshot']['name'] == 'Partner ERP'
        assert (
            by_action['HARD_DELETE']['snapshot']['url'] == 'https://example.com/hook-v2'
        )
        assert by_action['HARD_DELETE']['user_email'] == 'trace_admin@example.com'

    def test_the_signing_secret_never_reaches_the_log(
        self,
        client: TestClient,
        trace_headers: dict[str, str],
    ) -> None:
        created = client.post(
            ENDPOINTS,
            json={
                'name': 'Signed',
                'url': 'https://example.com/signed',
                'event_types': ['item.created'],
                'secret': 'sup3r-s3cret-value',
            },
            headers=trace_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        log = client.get('/api/v1/audit-log', headers=trace_headers)
        assert 'sup3r-s3cret-value' not in log.text

    async def test_the_breaker_cut_off_is_the_systems_act(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        """The breaker switches a channel off; nobody is named for it.

        A channel that went quiet by itself and one somebody turned off used
        to look the same from the outside — neither wrote anything.
        """
        from app.modules.webhooks._webhook_delivery import (
            _breaker_threshold_async,
            _update_stats_after_delivery,
        )

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org = Organization(name='Breaker Org', enabled_modules=['webhooks'])
            session.add(org)
            await session.flush()
            endpoint = WebhookEndpoint(
                organization_id=org.id,
                name='Flaky receiver',
                url='https://example.com/flaky',
                http_method='POST',
                event_types=['item.created'],
                max_retries=1,
                retry_backoff_seconds=1,
                timeout_seconds=5,
                is_active=True,
                consecutive_failures=2,
            )
            session.add(endpoint)
            await session.flush()
            from app.core.public_api import core_api

            await core_api.settings.set_bulk_async(
                session, org.id, 'webhooks', {'circuit_breaker_threshold': 3}
            )
            await session.commit()

            threshold = await _breaker_threshold_async(session, org.id)
            await _update_stats_after_delivery(
                session,
                endpoint,
                is_success=False,
                status_code=500,
                threshold=threshold,
            )
            await session.commit()

            assert endpoint.is_active is False

            entries = (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.organization_id == org.id,
                        AuditLog.target_type == 'webhook_endpoint',
                    )
                )
            ).all()
            assert len(entries) == 1
            entry = entries[0]
            assert entry.reason == 'circuit_breaker'
            # Nobody switched this channel off, so nobody is named — and
            # the system is, by the structured actor the screen reads.
            assert entry.user_id is None
            assert (entry.meta_data or {}).get('actor') == {'type': 'system'}
            snapshot = entry.snapshot or {}
            assert snapshot['name'] == 'Flaky receiver'
            assert snapshot['url'] == 'https://example.com/flaky'

    async def test_failures_past_the_threshold_journal_the_cut_off_once(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        """A cut-off is one event, however many probes fail after it.

        Test pings still reach a channel the breaker switched off, and each
        failing one used to write the same "disabled by the circuit breaker"
        row again — four identical System entries for one cut-off.
        """
        from app.modules.webhooks._webhook_delivery import _update_stats_after_delivery

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org = Organization(name='Repeat Org', enabled_modules=['webhooks'])
            session.add(org)
            await session.flush()
            endpoint = WebhookEndpoint(
                organization_id=org.id,
                name='Dead receiver',
                url='https://example.com/dead',
                http_method='POST',
                event_types=['item.created'],
                max_retries=1,
                retry_backoff_seconds=1,
                timeout_seconds=5,
                is_active=True,
            )
            session.add(endpoint)
            await session.commit()

            for _ in range(5):
                await _update_stats_after_delivery(
                    session, endpoint, is_success=False, status_code=500, threshold=2
                )
                await session.commit()

            assert endpoint.consecutive_failures == 5
            assert endpoint.is_active is False
            entries = (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.organization_id == org.id,
                        AuditLog.target_type == 'webhook_endpoint',
                    )
                )
            ).all()
            assert len(entries) == 1
            assert (entries[0].meta_data or {}).get('consecutive_failures') == 2

    async def test_saving_the_form_between_failures_does_not_journal_the_cut_off_twice(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        """Admin edits a cut-off channel, then presses Test: still one event.

        The edit form sends is_active on every save; sent unchanged it used
        to erase the cut-off mark the once-only guard reads.
        """
        from app.modules.webhooks._webhook_delivery import _update_stats_after_delivery
        from app.modules.webhooks.webhook_crud_service import update_endpoint_async

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org = Organization(name='Form Save Org', enabled_modules=['webhooks'])
            session.add(org)
            await session.flush()
            endpoint = WebhookEndpoint(
                organization_id=org.id,
                name='Dead receiver',
                url='https://example.com/dead',
                http_method='POST',
                event_types=['item.created'],
                max_retries=1,
                retry_backoff_seconds=1,
                timeout_seconds=5,
                is_active=True,
            )
            session.add(endpoint)
            await session.commit()

            for _ in range(3):
                await _update_stats_after_delivery(
                    session, endpoint, is_success=False, status_code=500, threshold=2
                )
                await session.commit()
            await update_endpoint_async(
                session, endpoint, name='Renamed receiver', is_active=False
            )
            await session.commit()
            await _update_stats_after_delivery(
                session, endpoint, is_success=False, status_code=500, threshold=2
            )
            await session.commit()

            entries = (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.organization_id == org.id,
                        AuditLog.target_type == 'webhook_endpoint',
                    )
                )
            ).all()
            assert len(entries) == 1

    async def test_a_passing_test_ping_keeps_the_count_that_tripped_the_breaker(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        """A test ping answers "does the receiver work", not "is the channel on".

        It zeroed the tally of a channel the breaker had cut off, and the
        card's sentence about the cut-off then read "after 0 consecutive
        errors" while the channel stayed off.
        """
        from app.modules.webhooks._webhook_delivery import _update_stats_after_delivery

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org = Organization(name='Ping Org', enabled_modules=['webhooks'])
            session.add(org)
            await session.flush()
            endpoint = WebhookEndpoint(
                organization_id=org.id,
                name='Cut off receiver',
                url='https://example.com/cut-off',
                http_method='POST',
                event_types=['item.created'],
                max_retries=1,
                retry_backoff_seconds=1,
                timeout_seconds=5,
                is_active=False,
                consecutive_failures=10,
                auto_disabled_at=datetime.now(UTC),
            )
            session.add(endpoint)
            await session.commit()

            await _update_stats_after_delivery(
                session, endpoint, is_success=True, status_code=200, threshold=10
            )

            assert endpoint.consecutive_failures == 10
            assert endpoint.is_active is False
            assert endpoint.auto_disabled_at is not None
            assert endpoint.last_status_code == 200

    def test_restoring_a_cut_off_channel_names_the_person(
        self,
        client: TestClient,
        db_session: Session,
        trace_org: Organization,
        trace_headers: dict[str, str],
    ) -> None:
        """The other half of the breaker: a person switched it back on."""
        endpoint = WebhookEndpoint(
            organization_id=trace_org.id,
            name='Restored receiver',
            url='https://example.com/restored',
            http_method='POST',
            event_types=['item.created'],
            max_retries=1,
            retry_backoff_seconds=1,
            timeout_seconds=5,
            is_active=False,
            consecutive_failures=10,
            # The breaker's mark: `_update_stats_after_delivery` sets it the
            # moment it switches the channel off, and a manual on/off decision
            # clears it. It is what tells the reactivation apart from a
            # hand-switched channel coming back on.
            auto_disabled_at=datetime.now(UTC),
        )
        db_session.add(endpoint)
        db_session.commit()
        db_session.refresh(endpoint)

        restored = client.post(
            f'{ENDPOINTS}/{endpoint.id}/reactivate', headers=trace_headers
        )
        assert restored.status_code == status.HTTP_200_OK, restored.text

        by_person = [
            e
            for e in _webhook_entries(client, trace_headers)
            if (e.get('meta_data') or {}).get('reactivated_after_circuit_breaker')
        ]
        assert len(by_person) == 1
        assert by_person[0]['user_email'] == 'trace_admin@example.com'
        assert by_person[0]['snapshot']['name'] == 'Restored receiver'

    def test_reactivating_a_hand_switched_channel_reads_as_a_plain_update(
        self,
        client: TestClient,
        db_session: Session,
        trace_org: Organization,
        trace_headers: dict[str, str],
    ) -> None:
        """A channel turned off by the edit form was never cut by the breaker.

        The Active toggle is a person's decision, and `update_endpoint_async`
        clears the breaker's mark when one is made — so a Reactivate that
        follows it must not claim the breaker did the switching. This test
        passes on dev only because dev never showed the flag; the sentence
        is this branch's, and so is the honesty about when it may appear.
        """
        endpoint = WebhookEndpoint(
            organization_id=trace_org.id,
            name='Hand-switched receiver',
            url='https://example.com/by-hand',
            http_method='POST',
            event_types=['item.created'],
            max_retries=1,
            retry_backoff_seconds=1,
            timeout_seconds=5,
            is_active=True,
            consecutive_failures=0,
        )
        db_session.add(endpoint)
        db_session.commit()
        db_session.refresh(endpoint)

        switched_off = client.put(
            f'{ENDPOINTS}/{endpoint.id}',
            json={'is_active': False},
            headers=trace_headers,
        )
        assert switched_off.status_code == status.HTTP_200_OK, switched_off.text

        restored = client.post(
            f'{ENDPOINTS}/{endpoint.id}/reactivate', headers=trace_headers
        )
        assert restored.status_code == status.HTTP_200_OK, restored.text

        entries = _webhook_entries(client, trace_headers)
        flagged = [
            e
            for e in entries
            if (e.get('meta_data') or {}).get('reactivated_after_circuit_breaker')
        ]
        assert flagged == []
        # The reactivation is still journalled — as the person's update it
        # is. The PUT's row carries the before/after diff; the reactivate
        # row's snapshot is flat.
        reactivated = [
            e
            for e in entries
            if e['action'] == 'UPDATE' and 'before' not in e['snapshot']
        ]
        assert len(reactivated) == 1
        assert reactivated[0]['user_email'] == 'trace_admin@example.com'


@pytest.mark.integration
class TestTheTraceSaysWhatChanged:
    """The journal answers what an edit changed, not only that one happened.

    An edit that replaced the signing secret and subscribed the channel to a
    second event left an entry whose two snapshots were identical: "Update"
    over a channel whose data could now leave by one more event and under a
    different signature, with nothing on the row saying so.
    """

    def _create(
        self,
        client: TestClient,
        headers: dict[str, str],
        **overrides: Any,
    ) -> str:
        body = {
            'name': 'Watched channel',
            'url': 'https://example.com/watched',
            'event_types': ['item.created'],
            'secret': 'first-secret-value',
        }
        body.update(overrides)
        created = client.post(ENDPOINTS, json=body, headers=headers)
        assert created.status_code == status.HTTP_201_CREATED, created.text
        return str(created.json()['id'])

    def _update_entry(
        self, client: TestClient, headers: dict[str, str]
    ) -> dict[str, Any]:
        entries = _webhook_entries(client, headers)
        updates = [e for e in entries if e['action'] == 'UPDATE']
        assert len(updates) == 1
        return updates[0]

    def test_an_edit_names_the_fields_that_moved(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        webhook_id = self._create(client, trace_headers)

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={
                'name': 'Watched channel v2',
                'http_method': 'PUT',
                'event_types': ['item.created', 'user.registered'],
                'is_active': False,
            },
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        entry = self._update_entry(client, trace_headers)
        snapshot = entry['snapshot']
        assert snapshot['before'] == {
            'name': 'Watched channel',
            'http_method': 'POST',
            'event_types': ['item.created'],
            'is_active': True,
        }
        assert snapshot['after'] == {
            'name': 'Watched channel v2',
            'http_method': 'PUT',
            'event_types': ['item.created', 'user.registered'],
            'is_active': False,
        }
        # The URL did not move, so it is not diffed — the destination the
        # channel has is the one it had.
        assert 'url' not in snapshot['before']

    def test_an_edit_of_the_delivery_limits_leaves_a_difference(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        """Max retries, timeout and backoff are edit-form fields like the rest."""
        webhook_id = self._create(client, trace_headers)
        before = client.get(f'{ENDPOINTS}/{webhook_id}', headers=trace_headers).json()

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={
                'max_retries': before['max_retries'] + 1,
                'timeout_seconds': before['timeout_seconds'] + 1,
                'retry_backoff_seconds': before['retry_backoff_seconds'] + 1,
            },
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        snapshot = self._update_entry(client, trace_headers)['snapshot']
        assert snapshot['before'] == {
            'max_retries': before['max_retries'],
            'timeout_seconds': before['timeout_seconds'],
            'retry_backoff_seconds': before['retry_backoff_seconds'],
        }
        assert snapshot['after'] == {
            'max_retries': before['max_retries'] + 1,
            'timeout_seconds': before['timeout_seconds'] + 1,
            'retry_backoff_seconds': before['retry_backoff_seconds'] + 1,
        }

    def test_a_rotated_secret_leaves_its_fact_not_its_value(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        webhook_id = self._create(client, trace_headers)

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={'secret': 'second-secret-value'},
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        entry = self._update_entry(client, trace_headers)
        snapshot = entry['snapshot']
        # Presence on both sides is the same word, so the walk drops it; the
        # fact that the credential turned over is the `fields` line.
        assert snapshot.get('fields') == ['secret']
        assert 'secret' not in snapshot.get('before', {})
        log = client.get('/api/v1/audit-log', headers=trace_headers)
        assert 'second-secret-value' not in log.text

    def test_a_cleared_secret_reads_as_cleared(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        webhook_id = self._create(client, trace_headers)

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={'secret': ''},
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        entry = self._update_entry(client, trace_headers)
        snapshot = entry['snapshot']
        assert snapshot['before'].get('secret') == 'set'
        assert snapshot['after'].get('secret') == 'absent'

    def test_a_quiet_edit_writes_no_difference_at_all(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        """An edit that changes nothing journalable says so by its silence.

        The masked echo the form sends back for an untouched secret is the
        shape a real edit arrives in; it must not read as a turn-over.
        """
        webhook_id = self._create(client, trace_headers)

        changed = client.put(
            f'{ENDPOINTS}/{webhook_id}',
            json={'secret': '**********'},
            headers=trace_headers,
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        entry = self._update_entry(client, trace_headers)
        assert entry['snapshot'].get('before') == {}
        assert entry['snapshot'].get('after') == {}
        assert 'fields' not in entry['snapshot']

    def test_creation_names_the_events_subscribed(
        self, client: TestClient, trace_headers: dict[str, str]
    ) -> None:
        self._create(
            client,
            trace_headers,
            event_types=['item.created', 'user.registered'],
        )

        entries = _webhook_entries(client, trace_headers)
        created = [e for e in entries if e['action'] == 'CREATE']
        assert len(created) == 1
        assert created[0]['snapshot']['event_types'] == [
            'item.created',
            'user.registered',
        ]
