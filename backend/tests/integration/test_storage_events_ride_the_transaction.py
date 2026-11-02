"""Storage, category, label, membership and module events ride the write.

``emit`` announces after the fact: a process that dies between the commit and
the XADD changed the data and told nobody, and an ``emit`` ahead of a rollback
announces something that did not happen. ``emit_transactional`` writes the
event to the outbox in the caller's transaction instead, so the two commit or
roll back together.

Two halves, because the test mode hides the difference. Under TESTING the bus
buffers the event on the session and dispatches it after the commit, so the
API half shows only that a subscriber still sees each event exactly once. The
outbox half turns TESTING off and reads the table, which is where the old
post-commit emit leaves nothing at all.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.contracts import LabelCodeItemDTO, LabelPoolCreateDTO, UserContextDTO
from app.core.public_api import core_api
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.user import User
from app.schemas.storage_location import (
    StorageLocationCreate,
    StorageReorgOperation,
    StorageReorgRequest,
)
from app.services.storage import _reorg as reorg_module
from app.services.storage import create_storage
from app.services.storage._reorg import execute_storage_reorg

pytestmark = pytest.mark.integration

STORAGES = '/api/v1/locations'


def _listen(event: str) -> list[Any]:
    received: list[Any] = []
    core_api.events.subscribe(event, received.append)
    return received


class TestSubscribersSeeEachEventOnce:
    """Webhook delivery rides this subscription: once per write, no more."""

    def test_create_update_delete_storage(self, client, auth_headers):
        created = _listen('location.created')
        updated = _listen('location.updated')
        deleted = _listen('location.deleted')

        response = client.post(STORAGES, json={'name': 'Cellar'}, headers=auth_headers)
        assert response.status_code == 201, response.text
        storage_id = response.json()['id']
        assert [p.location_id for p in created] == [storage_id]

        response = client.put(
            f'{STORAGES}/{storage_id}',
            json={'name': 'Cold cellar'},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert [p.location_id for p in updated] == [storage_id]

        response = client.delete(f'{STORAGES}/{storage_id}', headers=auth_headers)
        assert response.status_code in (200, 204), response.text
        assert [p.location_id for p in deleted] == [storage_id]

    def test_reorg_announces_each_create_move_and_delete_once(
        self, client, auth_headers
    ):
        first = client.post(STORAGES, json={'name': 'Old'}, headers=auth_headers)
        second = client.post(STORAGES, json={'name': 'Mover'}, headers=auth_headers)
        old_id, mover_id = first.json()['id'], second.json()['id']
        created = _listen('location.created')
        updated = _listen('location.updated')
        deleted = _listen('location.deleted')

        response = client.post(
            f'{STORAGES}/reorg',
            headers=auth_headers,
            json={
                'operations': [
                    {'op': 'create', 'temporary_id': 't', 'name': 'Fresh'},
                    {'op': 'move', 'id': mover_id, 'parent_id': 't'},
                    {'op': 'delete', 'id': old_id},
                ]
            },
        )

        body = response.json()
        assert body['applied'] is True, body
        assert [p.location_id for p in created] == [body['created']['t']]
        assert [p.location_id for p in updated] == [mover_id]
        assert [p.location_id for p in deleted] == [old_id]

    def test_a_refused_reorg_announces_nothing(self, client, auth_headers):
        site = client.post(STORAGES, json={'name': 'Site'}, headers=auth_headers)
        zone = client.post(
            STORAGES,
            json={'name': 'Zone', 'parent_id': site.json()['id']},
            headers=auth_headers,
        )
        updated = _listen('location.updated')

        response = client.post(
            f'{STORAGES}/reorg',
            headers=auth_headers,
            json={
                'operations': [
                    {
                        'op': 'move',
                        'id': site.json()['id'],
                        'parent_id': zone.json()['id'],
                    }
                ]
            },
        )

        assert response.json()['applied'] is False
        assert updated == []

    def test_category_label_and_module_writes(self, client, auth_headers):
        category_created = _listen('category.created')
        batches = _listen('label.batch_generated')

        response = client.post(
            '/api/v1/categories', json={'name': 'Spices'}, headers=auth_headers
        )
        assert response.status_code == 201, response.text
        assert len(category_created) == 1

        response = client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 2, 'label_type': 'GENERIC'},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        assert len(batches) == 1
        assert batches[0].count == 2


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any
) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(
            text('TRUNCATE event_outbox, organizations RESTART IDENTITY CASCADE')
        )
        await session.commit()
    return factory


@pytest.fixture
async def member(session_factory: async_sessionmaker[AsyncSession]) -> UserContextDTO:
    async with session_factory() as session:
        org = Organization(name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=[])
        session.add(org)
        await session.flush()
        user = User(
            email=f'outbox-{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        session.add(user)
        await session.commit()
        return UserContextDTO(id=user.id, organization_id=org.id)


async def _outbox_events(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        rows = await session.execute(text('SELECT event FROM event_outbox'))
        return sorted(row[0] for row in rows)


class TestTheEventIsAnOutboxRow:
    async def test_a_rolled_back_write_leaves_no_event(
        self, session_factory, member
    ) -> None:
        """The phantom: announce, then roll back. The old emit dispatched
        ``location.created`` for a location that never existed."""
        seen = _listen('location.created')
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await create_storage(
                    session, StorageLocationCreate(name='Phantom'), member
                )
                await session.rollback()

        assert seen == []
        assert await _outbox_events(session_factory) == []

    async def test_a_rollback_drops_the_event_buffered_for_the_test_dispatch(
        self, session_factory, member
    ) -> None:
        """Under TESTING the event waits on the session for ``flush_pending``;
        a rollback has to take it along, or the next flush announces a write
        that was never kept."""
        seen = _listen('location.created')
        async with session_factory() as session:
            await create_storage(session, StorageLocationCreate(name='Gone'), member)
            await session.rollback()
            await core_api.events.flush_pending_async(session)

        assert seen == []

    async def test_a_committed_write_leaves_its_event_for_the_relay(
        self, session_factory, member
    ) -> None:
        """The lost event: commit, then die before the XADD. With the event in
        the outbox the commit itself is what carries it."""
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await create_storage(
                    session, StorageLocationCreate(name='Kept'), member
                )
                await session.commit()

        assert await _outbox_events(session_factory) == ['location.created']

    async def test_a_reorg_batch_commits_its_events_with_its_writes(
        self, session_factory, member
    ) -> None:
        request = StorageReorgRequest(
            operations=[
                StorageReorgOperation(op='create', temporary_id='a', name='A'),
                StorageReorgOperation(op='create', temporary_id='b', name='B'),
            ]
        )
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                result = await execute_storage_reorg(session, request, member)
                await session.commit()

        assert result.applied is True
        assert await _outbox_events(session_factory) == [
            'location.created',
            'location.created',
        ]

    async def test_a_reorg_batch_that_fails_midway_leaves_no_event(
        self, session_factory, member
    ) -> None:
        """The batch runs in a savepoint: a failure after the events were
        written takes them back with the rest of the batch, and the caller's
        own commit then keeps nothing of it."""
        request = StorageReorgRequest(
            operations=[
                StorageReorgOperation(op='create', temporary_id='a', name='A'),
            ]
        )
        seen = _listen('location.created')
        real_emit = reorg_module._emit_events

        async def emit_then_fail(*args, **kwargs) -> None:
            await real_emit(*args, **kwargs)
            raise RuntimeError('the batch broke after its events')

        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                with patch.object(reorg_module, '_emit_events', emit_then_fail):
                    result = await execute_storage_reorg(session, request, member)
                await session.commit()

        assert result.applied is False
        assert seen == []
        assert await _outbox_events(session_factory) == []

    async def test_a_reorg_batch_whose_commit_is_refused_leaves_no_event(
        self, session_factory, member
    ) -> None:
        """The original scenario, with the commit where it now lives: the
        request's. The batch applied, the caller's commit failed, and the
        events that rode the transaction went with it."""
        request = StorageReorgRequest(
            operations=[
                StorageReorgOperation(op='create', temporary_id='a', name='A'),
            ]
        )
        seen = _listen('location.created')
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                result = await execute_storage_reorg(session, request, member)

                async def refuse() -> None:
                    raise RuntimeError('commit refused')

                with patch.object(session, 'commit', refuse):
                    with pytest.raises(RuntimeError, match='commit refused'):
                        await session.commit()
                await session.rollback()

        assert result.applied is True
        assert seen == []
        assert await _outbox_events(session_factory) == []


async def _label_rows(
    factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, Any]]:
    async with factory() as session:
        rows = await session.execute(
            text('SELECT short_code, printed_at FROM label_pool')
        )
        return sorted((row[0], row[1]) for row in rows)


class TestLabelWritesLeaveTheCommitToTheCaller:
    """A label route writes the labels and then records its event. If the
    service committed in between, a failure on the event left the labels saved
    and announced by nobody; the write has to stay open until the caller's one
    commit, so the event and the labels stand or fall together."""

    async def test_a_generated_pool_is_not_kept_until_the_caller_commits(
        self, session_factory, member
    ) -> None:
        async with session_factory() as session:
            labels = await core_api.labels.generate_pool_async(
                session, LabelPoolCreateDTO(count=2, label_type='GENERIC'), member
            )
            assert len(labels) == 2
            await session.rollback()

        assert await _label_rows(session_factory) == []

    async def test_labels_from_codes_are_not_kept_until_the_caller_commits(
        self, session_factory, member
    ) -> None:
        async with session_factory() as session:
            await core_api.labels.create_from_codes_async(
                session, [LabelCodeItemDTO(short_code='SN-1')], member
            )
            await session.rollback()

        assert await _label_rows(session_factory) == []

    async def test_marking_printed_is_not_kept_until_the_caller_commits(
        self, session_factory, member
    ) -> None:
        async with session_factory() as session:
            labels = await core_api.labels.create_from_codes_async(
                session, [LabelCodeItemDTO(short_code='SN-2')], member
            )
            await session.commit()
            await core_api.labels.mark_as_printed_by_ids_async(
                session, [labels[0].id], member.organization_id
            )
            await session.rollback()

        assert await _label_rows(session_factory) == [('SN-2', None)]

    async def test_labels_and_their_event_commit_together(
        self, session_factory, member
    ) -> None:
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await core_api.labels.generate_pool_async(
                    session, LabelPoolCreateDTO(count=1, label_type='GENERIC'), member
                )
                await core_api.events.emit_transactional_async(
                    session,
                    'label.batch_generated',
                    {
                        'organization_id': str(member.organization_id),
                        'count': 1,
                        'label_type': 'GENERIC',
                        'label_ids': [],
                        'created_by': str(member.id),
                    },
                )
                await session.commit()

        assert len(await _label_rows(session_factory)) == 1
        assert await _outbox_events(session_factory) == ['label.batch_generated']

    async def test_a_pool_collision_retries_without_touching_the_callers_work(
        self, session_factory, member
    ) -> None:
        """The retry used to roll the whole session back. It now undoes only
        its own batch, so what the caller wrote before survives it."""
        async with session_factory() as session:
            session.add(
                LabelPool(
                    short_code='KEEP',
                    organization_id=member.organization_id,
                    created_by=member.id,
                    is_assigned=False,
                    label_type='GENERIC',
                )
            )
            await session.flush()
            calls = {'n': 0}
            from app.services import label_service

            original = label_service._draw_unused_short_codes_async

            async def collide_once(db: AsyncSession, **kw: Any) -> list[str]:
                codes = await original(db, **kw)
                calls['n'] += 1
                if calls['n'] == 1:
                    # Two rows with one code: the flush at the end of the
                    # savepoint raises IntegrityError, the retry draws again.
                    db.add(
                        LabelPool(
                            short_code=codes[0],
                            organization_id=kw['organization_id'],
                            created_by=member.id,
                            is_assigned=False,
                            label_type='GENERIC',
                        )
                    )
                    db.add(
                        LabelPool(
                            short_code=codes[0],
                            organization_id=kw['organization_id'],
                            created_by=member.id,
                            is_assigned=False,
                            label_type='GENERIC',
                        )
                    )
                return codes

            with patch.object(
                label_service, '_draw_unused_short_codes_async', collide_once
            ):
                labels = await core_api.labels.generate_pool_async(
                    session, LabelPoolCreateDTO(count=1, label_type='GENERIC'), member
                )
            await session.commit()

        codes = [code for code, _ in await _label_rows(session_factory)]
        assert calls['n'] == 2
        assert 'KEEP' in codes
        assert labels[0].short_code in codes
