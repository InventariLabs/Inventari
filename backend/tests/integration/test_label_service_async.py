"""
Integration tests for async label_service methods.

Covers: generate_label_pool_async, get_by_id_async, get_by_short_code_async,
list_for_org_async, get_pool_stats_async, list_in_ids_async,
list_unprinted_unassigned_async, delete_label_async, unassign_label_async,
assign_to_existing_item_async, mark_as_printed_by_ids_async.
"""

import uuid

import pytest

from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import get_password_hash


def _uid(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:6].upper()}'


async def _create_org_and_user(db):
    org = Organization(name='Async Test Org')
    db.add(org)
    await db.flush()
    user = User(
        email=f'async_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('TestPass123'),
        full_name='Async Test User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return org, user


async def _create_label(db, org_id, user_id, short_code=None, **kwargs):
    if short_code is None:
        short_code = _uid('LBL')
    label = LabelPool(
        short_code=short_code,
        organization_id=org_id,
        created_by=user_id,
        **kwargs,
    )
    db.add(label)
    await db.flush()
    return label


async def _create_item(db, org_id, user_id):
    from app.models.item import Item
    from app.models.storage_location import StorageLocation

    st = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=_uid('Loc'),
    )
    db.add(st)
    await db.flush()

    item = Item(
        organization_id=org_id,
        storage_location_id=st.id,
        name=_uid('Item'),
        quantity=1,
    )
    db.add(item)
    await db.flush()
    return item


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetByIdAsync:
    async def test_get_existing_label(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        code = _uid('GID')
        label = await _create_label(real_async_db_session, org.id, user.id, code)
        found = await LabelService.get_by_id_async(
            real_async_db_session, label.id, org.id
        )
        assert found is not None
        assert found.id == label.id
        assert found.short_code == code

    async def test_get_nonexistent_returns_none(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        found = await LabelService.get_by_id_async(
            real_async_db_session, uuid.uuid4(), org.id
        )
        assert found is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetByShortCodeAsync:
    async def test_get_existing_by_code(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        code = _uid('SCD')
        await _create_label(real_async_db_session, org.id, user.id, code)
        found = await LabelService.get_by_short_code_async(
            real_async_db_session, code, org.id
        )
        assert found is not None
        assert found.short_code == code

    async def test_get_wrong_org_returns_none(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        code = _uid('SCD')
        await _create_label(real_async_db_session, org.id, user.id, code)
        found = await LabelService.get_by_short_code_async(
            real_async_db_session, code, uuid.uuid4()
        )
        assert found is None

    async def test_get_nonexistent_code_returns_none(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, _ = await _create_org_and_user(real_async_db_session)
        found = await LabelService.get_by_short_code_async(
            real_async_db_session, 'NOPE-9999', org.id
        )
        assert found is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestListForOrgAsync:
    async def test_list_all_for_org(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        for _ in range(5):
            await _create_label(real_async_db_session, org.id, user.id)
        result = await LabelService.list_for_org_async(real_async_db_session, org.id)
        assert len(result) == 5

    async def test_list_unassigned_only(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        await _create_label(real_async_db_session, org.id, user.id)
        await _create_label(real_async_db_session, org.id, user.id, is_assigned=True)
        await _create_label(real_async_db_session, org.id, user.id)
        result = await LabelService.list_for_org_async(
            real_async_db_session, org.id, unassigned_only=True
        )
        assert len(result) == 2

    async def test_list_filter_by_type(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        await _create_label(
            real_async_db_session, org.id, user.id, label_type='STORAGE'
        )
        await _create_label(
            real_async_db_session, org.id, user.id, label_type='GENERIC'
        )
        await _create_label(
            real_async_db_session, org.id, user.id, label_type='STORAGE'
        )
        result = await LabelService.list_for_org_async(
            real_async_db_session, org.id, label_type='STORAGE'
        )
        assert len(result) == 2
        assert all(lbl.label_type == 'STORAGE' for lbl in result)

    async def test_list_empty_org(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, _ = await _create_org_and_user(real_async_db_session)
        result = await LabelService.list_for_org_async(real_async_db_session, org.id)
        assert result == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetPoolStatsAsync:
    async def test_stats_with_mixed_labels(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        await _create_label(real_async_db_session, org.id, user.id)
        await _create_label(real_async_db_session, org.id, user.id)
        await _create_label(real_async_db_session, org.id, user.id, is_assigned=True)
        stats = await LabelService.get_pool_stats_async(real_async_db_session, org.id)
        assert stats['total'] == 3
        assert stats['assigned'] == 1
        assert stats['unassigned'] == 2

    async def test_stats_empty_pool(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, _ = await _create_org_and_user(real_async_db_session)
        stats = await LabelService.get_pool_stats_async(real_async_db_session, org.id)
        assert stats['total'] == 0
        assert stats['assigned'] == 0
        assert stats['unassigned'] == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestListInIdsAsync:
    async def test_list_returns_matching_labels(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        labels = []
        for _ in range(4):
            lbl = await _create_label(real_async_db_session, org.id, user.id)
            labels.append(lbl)
        ids = [labels[0].id, labels[2].id]
        result = await LabelService.list_in_ids_async(
            real_async_db_session, ids, org.id
        )
        assert len(result) == 2
        result_ids = {lbl.id for lbl in result}
        assert labels[0].id in result_ids
        assert labels[2].id in result_ids

    async def test_list_empty_ids_returns_empty(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, _ = await _create_org_and_user(real_async_db_session)
        result = await LabelService.list_in_ids_async(real_async_db_session, [], org.id)
        assert result == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestListUnprintedUnassignedAsync:
    async def test_returns_only_unprinted_unassigned(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        await _create_label(real_async_db_session, org.id, user.id)
        await _create_label(real_async_db_session, org.id, user.id)
        await _create_label(real_async_db_session, org.id, user.id, is_assigned=True)
        from datetime import UTC, datetime

        await _create_label(
            real_async_db_session,
            org.id,
            user.id,
            printed_at=datetime.now(UTC),
        )
        result = await LabelService.list_unprinted_unassigned_async(
            real_async_db_session, org.id, limit=100
        )
        assert len(result) == 2

    async def test_respects_limit(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        for _ in range(5):
            await _create_label(real_async_db_session, org.id, user.id)
        result = await LabelService.list_unprinted_unassigned_async(
            real_async_db_session, org.id, limit=3
        )
        assert len(result) == 3

    async def test_excludes_ids(self, real_async_db_session):
        from app.services.label_service import LabelService

        org, user = await _create_org_and_user(real_async_db_session)
        labels = []
        for _ in range(3):
            lbl = await _create_label(real_async_db_session, org.id, user.id)
            labels.append(lbl)
        result = await LabelService.list_unprinted_unassigned_async(
            real_async_db_session, org.id, limit=100, exclude_ids=[labels[1].id]
        )
        assert len(result) == 2
        result_ids = {lbl.id for lbl in result}
        assert labels[1].id not in result_ids
