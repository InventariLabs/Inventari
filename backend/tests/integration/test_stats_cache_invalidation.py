"""A cached overview answers from the rows, not from history.

``cache_invalidate_org_queries`` had no production caller: the analytics
read-models cached for 300 s kept answering with the numbers as they stood
when the cache was primed. After a location was re-purposed, the overview
still counted the stock that had just left it — three different answers to
"how much do I have" on one screen — and the vulture whitelist hid the
dead function from the gate that would have said so.

Invalidation is a version bump, so the assertions below ask
whether the organization's *current* overview key holds an answer rather
than whether a particular key name exists: the name was an implementation
detail — and asking about the name is what made a keyspace walk look like
the contract.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import cache as cache_module
from app.core.contracts import AuditAction, AuditTargetType
from app.services import audit_service
from app.services.audit_service import log_action_async
from app.services.token_service import create_access_token
from tests.integration._fake_redis import FakeRedis

pytestmark = pytest.mark.integration


class _DownRedis:
    """A Redis that answers every command with a connection error."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError('redis is down')

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        raise ConnectionError('redis is down')

    async def incr(self, key: str) -> int:
        raise ConnectionError('redis is down')


@pytest.fixture
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(cache_module, '_redis', redis)
    return redis


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def committed_location(real_async_db_session, async_test_storage_location):
    await real_async_db_session.commit()
    return async_test_storage_location


@pytest.fixture
async def stocked_location(real_async_client, admin, committed_location):
    """A location holding two products, created through the API."""
    item_ids: list[str] = []
    for name in ('Cache Milk', 'Cache Bread'):
        response = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': name,
                'location_id': str(committed_location.id),
                'quantity': 1,
            },
            headers=_auth(admin),
        )
        assert response.status_code == 201
        item_ids.append(response.json()['id'])
    return committed_location, item_ids


@pytest.mark.asyncio
class TestTheCacheFollowsTheRows:
    async def test_a_soft_delete_leaves_the_overview_agreeing_with_the_list(
        self,
        real_async_client,
        admin,
        fake_redis,
        stocked_location,
    ):
        location, item_ids = stocked_location
        org_id: UUID = admin.organization_id
        # The overview was cached for 300 s and nothing ever
        # invalidated it. The journaled act below must throw that answer
        # away, or the dashboard keeps counting stock that is gone.
        primed = await real_async_client.get(
            '/api/v1/stats/overview', headers=_auth(admin)
        )
        assert primed.status_code == 200
        assert primed.json()['total_items'] == 2
        # The cache is primed: the key the overview reads under holds it.
        primed_key = await cache_module.org_query_key(org_id, 'overview')
        assert await fake_redis.get(primed_key) is not None

        removed = await real_async_client.delete(
            f'/api/v1/items/{item_ids[0]}',
            headers=_auth(admin),
        )
        assert removed.status_code == 204

        # The journaled act moved the org past its cached answer, without
        # walking the keyspace on the way.
        assert await cache_module.org_query_key(org_id, 'overview') != primed_key
        assert 'scan_iter' not in fake_redis.commands

        after = await real_async_client.get(
            '/api/v1/stats/overview', headers=_auth(admin)
        )
        listed = await real_async_client.get('/api/v1/items', headers=_auth(admin))
        assert after.json()['total_items'] == 1
        assert listed.json()['total'] == after.json()['total_items']

    async def test_a_bulk_update_invalidates_without_a_journal_entry(
        self,
        real_async_client,
        admin,
        fake_redis,
        stocked_location,
        real_async_db_session,
    ):
        from app.models.item import Item

        org_id: UUID = admin.organization_id
        primed = await real_async_client.get(
            '/api/v1/stats/overview', headers=_auth(admin)
        )
        assert primed.json()['total_items'] == 2
        primed_key = await cache_module.org_query_key(org_id, 'overview')
        assert await fake_redis.get(primed_key) is not None

        # Read the ids the way the client's own session sees them.
        await real_async_db_session.commit()
        item_rows = list(
            (
                await real_async_db_session.execute(
                    select(Item.id).where(Item.organization_id == org_id)
                )
            )
            .scalars()
            .all()
        )

        bulk = await real_async_client.patch(
            '/api/v1/items/bulk',
            json={
                'item_ids': [str(i) for i in item_rows],
                'update_data': {'brand': 'Cache Test'},
            },
            headers=_auth(admin),
        )
        assert bulk.status_code == 200

        assert await cache_module.org_query_key(org_id, 'overview') != primed_key

    async def test_a_broken_cache_does_not_fail_the_write(
        self,
        real_async_client,
        admin,
        stocked_location,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Redis down: the delete still happens, the answer just recomputes."""
        location, item_ids = stocked_location
        monkeypatch.setattr(cache_module, '_redis', _DownRedis())

        removed = await real_async_client.delete(
            f'/api/v1/items/{item_ids[0]}',
            headers=_auth(admin),
        )
        assert removed.status_code == 204

        gone = await real_async_client.get(
            f'/api/v1/items/{item_ids[0]}', headers=_auth(admin)
        )
        assert gone.status_code == 404, 'the write must survive a cache outage'


@pytest.mark.asyncio
class TestWhichEntriesInvalidate:
    """The invalidation is skipped where it cannot have anything to do.

    Every cached read-model is built from stock, catalogue or custody rows,
    so an entry about who may access the organization — or about somebody's
    own working note — cannot have made one stale. Those entries used to pay
    for the invalidation anyway, and since that invalidation walked the
    keyspace, a role change cost the whole installation a SCAN.
    """

    @pytest.mark.parametrize('target', [AuditTargetType.ROLE, 'role'])
    async def test_an_access_entry_leaves_the_cached_answer_reachable(
        self,
        target,
        real_async_db_session,
        admin,
        fake_redis,
    ):
        """A role change logs, and what the cache answers is untouched.

        Parametrised over the enum and the plain string because call sites
        predating :class:`AuditTargetType` still pass literals, and both
        spellings have to meet the same list.
        """
        org_id: UUID = admin.organization_id
        key = await cache_module.org_query_key(org_id, 'overview')
        await fake_redis.set(key, json.dumps({'total_items': 2}))

        await log_action_async(
            real_async_db_session,
            organization_id=org_id,
            user_id=admin.id,
            action=AuditAction.UPDATE,
            target_type=target,
            target_id=uuid4(),
        )
        await real_async_db_session.commit()

        assert await cache_module.org_query_key(org_id, 'overview') == key
        assert await fake_redis.get(key) == json.dumps({'total_items': 2})

    async def test_a_state_entry_makes_it_unreachable(
        self,
        real_async_db_session,
        admin,
        fake_redis,
    ):
        """The control: an entry about an item does invalidate."""
        org_id: UUID = admin.organization_id
        key = await cache_module.org_query_key(org_id, 'overview')
        await fake_redis.set(key, json.dumps({'total_items': 2}))

        await log_action_async(
            real_async_db_session,
            organization_id=org_id,
            user_id=admin.id,
            action=AuditAction.QUANTITY_CHANGE,
            target_type=AuditTargetType.ITEM,
            target_id=uuid4(),
        )
        await real_async_db_session.commit()

        assert await cache_module.org_query_key(org_id, 'overview') != key

    async def test_a_module_toggle_and_an_org_setting_still_invalidate(
        self,
        real_async_db_session,
        admin,
        fake_redis,
    ):
        """Both look like access and neither is: a module decides which rows
        the stats count, and the organization carries the currency a
        valuation may sum. Read here, they cannot be skipped."""
        org_id: UUID = admin.organization_id

        for target in (AuditTargetType.MODULE, AuditTargetType.ORGANIZATION):
            key = await cache_module.org_query_key(org_id, 'overview')
            await fake_redis.set(key, json.dumps({'total_items': 2}))

            await log_action_async(
                real_async_db_session,
                organization_id=org_id,
                user_id=admin.id,
                action=AuditAction.UPDATE,
                target_type=target,
                target_id=uuid4(),
            )
            await real_async_db_session.commit()

            assert await cache_module.org_query_key(org_id, 'overview') != key, (
                f'{target} must invalidate the analytics cache'
            )


def test_the_skip_list_is_a_decision_and_is_pinned() -> None:
    """Which targets skip the invalidation is recorded, not drifted into.

    If this fails, the list changed: decide whether the new (or removed)
    target can move a cached read-model, then update this test in the same
    change and say why in it. Adding to the list silently means an
    organization's dashboard keeps answering with stale numbers until the
    TTL runs out; removing from it means a write pays for a cache it cannot
    have made stale.
    """
    assert audit_service._ANALYTICS_NEUTRAL_TARGETS == frozenset(
        {
            AuditTargetType.ORG_MEMBER.value,
            AuditTargetType.ROLE.value,
            AuditTargetType.INVITATION.value,
            AuditTargetType.API_KEY.value,
            AuditTargetType.WEBHOOK_ENDPOINT.value,
            AuditTargetType.RECIPE.value,
            AuditTargetType.MEAL_PLAN.value,
            AuditTargetType.RECIPE_COLLECTION.value,
            AuditTargetType.SHOPPING_LIST.value,
        }
    )
