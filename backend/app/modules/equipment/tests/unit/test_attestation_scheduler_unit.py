"""Unit tests for ``equipment._attestation_scheduler``.

The worker talks to the database only through the injected ``AsyncSession``
and to CoreAPI / ``send_reminders`` through module references, so everything
here is a plain mock — no DB and no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.equipment._attestation_scheduler import (
    run_attestation_reminder_self_contained,
    run_scheduled_reminder_check_async,
)


def _campaign(
    *,
    deadline: datetime,
    reminder_days_before: int = 3,
    last_reminder_sent_at: datetime | None = None,
) -> MagicMock:
    campaign = MagicMock()
    campaign.id = 'campaign-id'
    campaign.organization_id = 'org-id'
    campaign.created_by = 'user-id'
    campaign.deadline = deadline
    campaign.reminder_days_before = reminder_days_before
    campaign.last_reminder_sent_at = last_reminder_sent_at
    return campaign


def _stub_db(campaigns: list[MagicMock], *, expired_rowcount: int = 0) -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()

    expired_result = MagicMock()
    expired_result.rowcount = expired_rowcount
    db.execute = AsyncMock(return_value=expired_result)

    active_result = MagicMock()
    active_result.all = MagicMock(return_value=campaigns)
    db.scalars = AsyncMock(return_value=active_result)
    return db


@pytest.mark.unit
class TestRunScheduledReminderCheck:
    async def test_expires_responses_and_commits_without_campaigns(self) -> None:
        db = _stub_db([], expired_rowcount=2)
        await run_scheduled_reminder_check_async(db)
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_zero_expired_responses_still_commits(self) -> None:
        db = _stub_db([], expired_rowcount=0)
        await run_scheduled_reminder_check_async(db)
        db.commit.assert_awaited_once()

    async def test_campaign_deadline_too_far_is_skipped(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=10))
        db = _stub_db([campaign])
        with patch(
            'app.modules.equipment._attestation_scheduler.send_reminders',
            new_callable=AsyncMock,
        ) as mock_send:
            await run_scheduled_reminder_check_async(db)
        mock_send.assert_not_awaited()

    async def test_campaign_recent_reminder_is_skipped(self) -> None:
        campaign = _campaign(
            deadline=datetime.now(UTC) + timedelta(days=1),
            last_reminder_sent_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db = _stub_db([campaign])
        with patch(
            'app.modules.equipment._attestation_scheduler.send_reminders',
            new_callable=AsyncMock,
        ) as mock_send:
            await run_scheduled_reminder_check_async(db)
        mock_send.assert_not_awaited()

    async def test_campaign_sends_reminders_with_creator_lang(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=1))
        db = _stub_db([campaign])

        mock_core = MagicMock()
        creator = MagicMock()
        creator.preferred_language = 'pl'
        mock_core.users.get_full_async = AsyncMock(return_value=creator)

        with (
            patch(
                'app.modules.equipment._attestation_scheduler.send_reminders',
                new_callable=AsyncMock,
                return_value={'reminders_sent': 2},
            ) as mock_send,
            patch('app.core.public_api.core_api', mock_core),
            patch.object(
                __import__('app.config', fromlist=['settings']).settings,
                'FRONTEND_URL',
                'https://ui.example',
                create=True,
            ),
        ):
            await run_scheduled_reminder_check_async(db)

        mock_send.assert_awaited_once_with(
            db,
            campaign.id,
            campaign.organization_id,
            'https://ui.example',
            lang='pl',
        )
        db.commit.assert_awaited_once()

    async def test_creator_none_defaults_lang_to_english(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=1))
        db = _stub_db([campaign])
        mock_core = MagicMock()
        mock_core.users.get_full_async = AsyncMock(return_value=None)

        with (
            patch(
                'app.modules.equipment._attestation_scheduler.send_reminders',
                new_callable=AsyncMock,
                return_value={'reminders_sent': 1},
            ) as mock_send,
            patch('app.core.public_api.core_api', mock_core),
        ):
            await run_scheduled_reminder_check_async(db)

        assert mock_send.call_args.kwargs['lang'] == 'en'

    async def test_creator_unsupported_lang_defaults_to_english(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=1))
        db = _stub_db([campaign])
        mock_core = MagicMock()
        creator = MagicMock()
        creator.preferred_language = 'xx'
        mock_core.users.get_full_async = AsyncMock(return_value=creator)

        with (
            patch(
                'app.modules.equipment._attestation_scheduler.send_reminders',
                new_callable=AsyncMock,
                return_value={'reminders_sent': 1},
            ) as mock_send,
            patch('app.core.public_api.core_api', mock_core),
        ):
            await run_scheduled_reminder_check_async(db)

        assert mock_send.call_args.kwargs['lang'] == 'en'

    async def test_creator_lookup_error_defaults_to_english(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=1))
        db = _stub_db([campaign])
        mock_core = MagicMock()
        mock_core.users.get_full_async = AsyncMock(side_effect=RuntimeError('db down'))

        with (
            patch(
                'app.modules.equipment._attestation_scheduler.send_reminders',
                new_callable=AsyncMock,
                return_value={'reminders_sent': 1},
            ) as mock_send,
            patch('app.core.public_api.core_api', mock_core),
        ):
            await run_scheduled_reminder_check_async(db)

        assert mock_send.call_args.kwargs['lang'] == 'en'

    async def test_send_reminders_error_does_not_crash_worker(self) -> None:
        campaign = _campaign(deadline=datetime.now(UTC) + timedelta(days=1))
        db = _stub_db([campaign])
        mock_core = MagicMock()
        mock_core.users.get_full_async = AsyncMock(return_value=None)

        with (
            patch(
                'app.modules.equipment._attestation_scheduler.send_reminders',
                new_callable=AsyncMock,
                side_effect=RuntimeError('smtp down'),
            ),
            patch('app.core.public_api.core_api', mock_core),
        ):
            await run_scheduled_reminder_check_async(db)

        db.commit.assert_awaited_once()


@pytest.mark.unit
class TestRunAttestationReminderSelfContained:
    async def test_skips_when_session_factory_not_initialized(self) -> None:
        with patch('app.core.db_facade.AsyncSessionLocal', None):
            await run_attestation_reminder_self_contained()

    async def test_runs_check_with_new_session(self) -> None:
        db = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=cm)

        with (
            patch('app.core.db_facade.AsyncSessionLocal', session_factory),
            patch(
                'app.modules.equipment._attestation_scheduler.run_scheduled_reminder_check_async',
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            await run_attestation_reminder_self_contained()

        mock_check.assert_awaited_once_with(db)
