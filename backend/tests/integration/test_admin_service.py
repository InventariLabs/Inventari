"""
Integration tests for AdminService.

Tests cover:
- get_system_summary: user/org counts, 24h actions, AI usage totals
- get_ai_usage_stats: usage breakdown by org, user, model
- get_activity_stats: daily action timeline
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.ai_usage_log import AIUsageLog
from app.models.item_history import ItemHistory
from app.services.admin_service import AdminService

ASYNC_URL = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)

admin_service = AdminService()


@pytest.fixture
async def async_session():
    """Provide an AsyncSession connected to the test database.

    Does NOT depend on db_session directly to avoid pytest-asyncio teardown
    deadlocks. The schema is guaranteed to exist because the test also
    requests db_session through other fixtures (test_user, test_household, etc.).
    Explicitly rolls back to release locks before db_session TRUNCATE runs.
    """
    engine = create_async_engine(ASYNC_URL, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _seed_ai_logs(db: Session, org_id: uuid.UUID, user_id: uuid.UUID, count: int = 3):
    for i in range(count):
        db.add(
            AIUsageLog(
                user_id=user_id,
                organization_id=org_id,
                model_name=f'model-{i % 2}',
                provider='test-provider',
                prompt_tokens=100 + i,
                completion_tokens=50 + i,
                total_tokens=150 + i * 2,
                estimated_cost_usd=0.001 * (i + 1),
                action_type='extract_label' if i % 2 == 0 else 'chat',
            )
        )
    db.commit()


def _seed_item_history(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    count: int = 2,
):
    for i in range(count):
        db.add(
            ItemHistory(
                organization_id=org_id,
                item_id=item_id,
                user_id=user_id,
                action='CREATED',
                created_at=datetime.now(UTC) - timedelta(hours=i),
            )
        )
    db.commit()


@pytest.mark.integration
@pytest.mark.async_db
class TestAdminServiceGetSystemSummary:
    """Tests for AdminService.get_system_summary."""

    async def test_empty_database_returns_zeros(
        self, db_session: Session, async_session: AsyncSession
    ):
        result = await admin_service.get_system_summary(async_session)

        assert result['counts']['users'] == 0
        assert result['counts']['organizations'] == 0
        assert result['counts']['actions_24h'] == 0
        assert result['ai_usage']['total_calls'] == 0
        assert result['ai_usage']['total_tokens'] == 0
        assert result['ai_usage']['total_cost_usd'] == 0.0

    async def test_counts_users_and_orgs(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        result = await admin_service.get_system_summary(async_session)

        assert result['counts']['users'] >= 1
        assert result['counts']['organizations'] >= 1

    async def test_counts_actions_24h(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
        test_item,
    ):
        _seed_item_history(db_session, test_household.id, test_user.id, test_item.id, 3)

        result = await admin_service.get_system_summary(async_session)

        assert result['counts']['actions_24h'] >= 3

    async def test_ai_usage_aggregation(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        _seed_ai_logs(db_session, test_household.id, test_user.id, 4)

        result = await admin_service.get_system_summary(async_session)

        assert result['ai_usage']['total_calls'] >= 4
        assert result['ai_usage']['total_tokens'] > 0
        assert result['ai_usage']['total_cost_usd'] > 0.0

    async def test_returns_expected_structure(
        self,
        db_session: Session,
        async_session: AsyncSession,
    ):
        result = await admin_service.get_system_summary(async_session)

        assert 'counts' in result
        assert 'ai_usage' in result
        assert 'users' in result['counts']
        assert 'organizations' in result['counts']
        assert 'actions_24h' in result['counts']
        assert 'total_calls' in result['ai_usage']
        assert 'total_tokens' in result['ai_usage']
        assert 'total_cost_usd' in result['ai_usage']


@pytest.mark.integration
@pytest.mark.async_db
class TestAdminServiceGetAiUsageStats:
    """Tests for AdminService.get_ai_usage_stats."""

    async def test_empty_returns_empty_lists(
        self, db_session: Session, async_session: AsyncSession
    ):
        result = await admin_service.get_ai_usage_stats(async_session, days=7)

        assert result['period_days'] == 7
        assert result['by_organization'] == []
        assert result['by_user'] == []
        assert result['by_model'] == []

    async def test_groups_by_model(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        _seed_ai_logs(db_session, test_household.id, test_user.id, 4)

        result = await admin_service.get_ai_usage_stats(async_session, days=30)

        assert len(result['by_model']) >= 2
        models = [m['model'] for m in result['by_model']]
        assert 'model-0' in models
        assert 'model-1' in models

    async def test_groups_by_user(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        _seed_ai_logs(db_session, test_household.id, test_user.id, 2)

        result = await admin_service.get_ai_usage_stats(async_session, days=30)

        assert len(result['by_user']) >= 1
        assert result['by_user'][0]['email'] is not None
        assert result['by_user'][0]['calls'] >= 2

    async def test_groups_by_organization(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        _seed_ai_logs(db_session, test_household.id, test_user.id, 2)

        result = await admin_service.get_ai_usage_stats(async_session, days=30)

        assert len(result['by_organization']) >= 1
        assert result['by_organization'][0]['calls'] >= 2

    async def test_custom_days_parameter(
        self,
        db_session: Session,
        async_session: AsyncSession,
    ):
        result = await admin_service.get_ai_usage_stats(async_session, days=1)

        assert result['period_days'] == 1

    async def test_each_entry_has_required_fields(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
    ):
        _seed_ai_logs(db_session, test_household.id, test_user.id, 1)

        result = await admin_service.get_ai_usage_stats(async_session, days=30)

        for entry in result['by_model']:
            assert 'model' in entry
            assert 'calls' in entry
            assert 'tokens' in entry
            assert 'cost' in entry

        for entry in result['by_organization']:
            assert 'name' in entry
            assert 'calls' in entry
            assert 'tokens' in entry
            assert 'cost' in entry

        for entry in result['by_user']:
            assert 'email' in entry
            assert 'calls' in entry
            assert 'tokens' in entry
            assert 'cost' in entry


@pytest.mark.integration
@pytest.mark.async_db
class TestAdminServiceGetActivityStats:
    """Tests for AdminService.get_activity_stats."""

    async def test_empty_returns_empty_timeline(
        self, db_session: Session, async_session: AsyncSession
    ):
        result = await admin_service.get_activity_stats(async_session, days=7)

        assert 'timeline' in result
        assert result['timeline'] == []

    async def test_returns_daily_counts(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
        test_item,
    ):
        _seed_item_history(db_session, test_household.id, test_user.id, test_item.id, 3)

        result = await admin_service.get_activity_stats(async_session, days=7)

        assert len(result['timeline']) >= 1
        for entry in result['timeline']:
            assert 'date' in entry
            assert 'count' in entry
            assert entry['count'] >= 1

    async def test_custom_days_parameter(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
        test_item,
    ):
        _seed_item_history(db_session, test_household.id, test_user.id, test_item.id, 1)

        result = await admin_service.get_activity_stats(async_session, days=1)

        assert 'timeline' in result
        assert len(result['timeline']) >= 1

    async def test_old_actions_excluded(
        self,
        db_session: Session,
        async_session: AsyncSession,
        test_user,
        test_household,
        test_item,
    ):
        old = ItemHistory(
            organization_id=test_household.id,
            item_id=test_item.id,
            user_id=test_user.id,
            action='CREATED',
            created_at=datetime.now(UTC) - timedelta(days=90),
        )
        db_session.add(old)
        db_session.commit()

        result = await admin_service.get_activity_stats(async_session, days=7)

        for entry in result['timeline']:
            assert entry['count'] >= 0
