"""
Unit tests for notification_worker using mock core_api.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.equipment.notification_worker import (
    MAINTENANCE_WARNING_DAYS,
    WARRANTY_WARNING_DAYS,
    _check_maintenance,
    _check_overdue,
    _check_warranty_async,
    _get_warning_windows,
    run_equipment_notification_check_async,
)


def _org_clock(mock_core: Any) -> None:
    """Answer the worker's "what day is it here?" the way Core would.

    The worker no longer reads the server's ``date.today()``; it asks the
    organization. With ``core_api`` mocked wholesale that question comes back
    as a MagicMock, so these tests state the answer — UTC, the same day the
    fixtures above build their dates from.
    """
    mock_core.organizations.today_async = AsyncMock(return_value=date.today())
    # The overdue check reads the expected return on the org's clock
    # (review 2026-09-23); UTC matches the plain dates these fixtures build.
    mock_core.organizations.timezone_async = AsyncMock(return_value=UTC)
    mock_core.organizations.window_start_async = AsyncMock(
        return_value=datetime.combine(date.today(), time.min, tzinfo=UTC)
    )


def _mock_db() -> MagicMock:
    """A mock session that can answer the one real query the worker makes.

    The worker asks the organization what day it is, and that lookup reads
    ``Organization.timezone`` off the session — so a bare ``MagicMock`` hands
    ``await`` a non-awaitable. UTC keeps these tests on the same day as the
    ``date.today()`` the fixtures above build their dates from.
    """
    db = MagicMock()
    db.scalar = AsyncMock(return_value='UTC')
    return db


def _mock_assignment(
    *,
    days_overdue: int = 5,
    item_name: str = 'Laptop',
    assigned_to: str = 'John',
    org_id: Any = None,
) -> MagicMock:
    a = MagicMock()
    a.id = uuid4()
    a.item_id = uuid4()
    a.organization_id = org_id or uuid4()
    a.assigned_to_name = assigned_to
    a.assignee_partner = None
    a.checkout_location = None
    a.checked_in_at = None
    a.expected_return_at = date.today() - timedelta(days=days_overdue)
    a.item = MagicMock()
    a.item.name = item_name
    return a


def _mock_maintenance_log(
    *,
    days_until: int = 3,
    item_name: str = 'Server',
    maintenance_type: str = 'INSPECTION',
) -> MagicMock:
    log = MagicMock()
    log.id = uuid4()
    log.item_id = uuid4()
    log.organization_id = uuid4()
    log.maintenance_type = maintenance_type
    log.next_maintenance_at = date.today() + timedelta(days=days_until)
    log.item = MagicMock()
    log.item.name = item_name
    return log


class _AsyncScalarIterator:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)
        self._index = 0

    def __aiter__(self) -> Any:
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


def _mock_scalars_stream(items: list[Any]) -> AsyncMock:
    scalar_result = _AsyncScalarIterator(items)
    stream_result = MagicMock()
    stream_result.scalars.return_value = scalar_result
    return stream_result


@pytest.mark.unit
class TestCheckOverdue:
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_sends_notification_for_overdue(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        assignment = _mock_assignment(days_overdue=5, org_id=org_id)
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=False
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()
        mock_core.notifications.publish_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([assignment]))

        await _check_overdue(db, org_id)
        mock_core.notifications.notify_org_admins_async.assert_called_once()
        mock_core.notifications.publish_async.assert_called_once()
        args = mock_core.notifications.notify_org_admins_async.call_args
        # The title is a language table now — the recipient's own
        # language decides which entry is stored.
        assert 'Overdue' in args[1]['title']['en']
        assert 'Zaległy' in args[1]['title']['pl']
        assert (
            args[1]['content']['en']
            == 'Laptop, assigned to John, was due back 5 day(s) ago.'
        )

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_a_deployment_sentence_names_the_place_no_hole(
        self, mock_core: Any
    ) -> None:
        """A deployment can carry a planned return date, and the alert is
        the one place with no screen to fall back on — the sentence itself
        has to name the place and stand on its own."""
        _org_clock(mock_core)
        org_id = uuid4()
        assignment = _mock_assignment(days_overdue=4, org_id=org_id, assigned_to='')
        assignment.checkout_location = MagicMock()
        assignment.checkout_location.name = 'Server Rack A'
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=False
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()
        mock_core.notifications.publish_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([assignment]))

        await _check_overdue(db, org_id)
        content = mock_core.notifications.notify_org_admins_async.call_args[1][
            'content'
        ]
        assert (
            content['en']
            == 'Laptop, standing in Server Rack A, was due back 4 day(s) ago.'
        )
        assert 'Server Rack A' in content['pl']
        for lang, sentence in content.items():
            assert '{' not in sentence and '}' not in sentence, lang
            assert 'Server Rack A' in sentence, lang

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_skips_when_no_overdue(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([]))

        await _check_overdue(db, uuid4())
        mock_core.notifications.notify_org_admins_async.assert_not_called()


@pytest.mark.unit
class TestCheckMaintenance:
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_sends_notification_for_upcoming(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        log = _mock_maintenance_log(days_until=3)
        item_ids = {log.item_id}
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=False
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()
        mock_core.notifications.publish_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([log]))

        with patch(
            'app.modules.equipment.notification_worker._get_equipment_item_ids',
            new_callable=AsyncMock,
            return_value=item_ids,
        ):
            await _check_maintenance(db, org_id, days=7)
            mock_core.notifications.notify_org_admins_async.assert_called_once()
            mock_core.notifications.publish_async.assert_called_once()
            args = mock_core.notifications.notify_org_admins_async.call_args
            assert 'Maintenance' in args[1]['title']['en']
        assert 'przegląd' in args[1]['title']['pl']

    async def test_skips_when_no_equipment_items(self) -> None:
        db = _mock_db()

        with patch(
            'app.modules.equipment.notification_worker._get_equipment_item_ids',
            new_callable=AsyncMock,
            return_value=set(),
        ):
            await _check_maintenance(db, uuid4(), days=7)
            db.stream.assert_not_called()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_skips_log_past_window(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        log = _mock_maintenance_log(days_until=30)
        item_ids = {log.item_id}

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([log]))

        with patch(
            'app.modules.equipment.notification_worker._get_equipment_item_ids',
            new_callable=AsyncMock,
            return_value=item_ids,
        ):
            await _check_maintenance(db, org_id, days=7)
            mock_core.notifications.notify_org_admins_async.assert_not_called()


@pytest.mark.unit
class TestRunNotificationCheckAsync:
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_skips_orgs_without_equipment_module(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org = MagicMock()
        org.id = uuid4()
        mock_core.organizations.list_all_async = AsyncMock(return_value=[org])
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        db = _mock_db()
        await run_equipment_notification_check_async(db)
        mock_core.organizations.is_module_enabled_async.assert_called_once_with(
            db, org.id, 'equipment'
        )

    @patch('app.modules.equipment.notification_worker._check_maintenance')
    @patch('app.modules.equipment.notification_worker._check_overdue')
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_checks_overdue_and_maintenance_for_enabled_org(
        self, mock_core: Any, mock_overdue: Any, mock_maintenance: Any
    ) -> None:
        org = MagicMock()
        org.id = uuid4()
        mock_core.organizations.list_all_async = AsyncMock(return_value=[org])
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=True)
        mock_core.settings.get_async = AsyncMock(return_value=None)
        db = AsyncMock()
        with patch(
            'app.modules.equipment.notification_worker._check_warranty_async',
        ) as mock_warranty:
            await run_equipment_notification_check_async(db)
            mock_warranty.assert_called_once_with(db, org.id, days=30)
            mock_overdue.assert_called_once_with(db, org.id)
            mock_maintenance.assert_called_once_with(db, org.id, days=7)
            db.commit.assert_awaited_once()

    @patch('app.modules.equipment.notification_worker._check_maintenance')
    @patch('app.modules.equipment.notification_worker._check_overdue')
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_exception_in_check_does_not_crash(
        self, mock_core: Any, mock_overdue: Any, mock_maintenance: Any
    ) -> None:
        org = MagicMock()
        org.id = uuid4()
        mock_core.organizations.list_all_async = AsyncMock(return_value=[org])
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=True)
        mock_core.settings.get_async = AsyncMock(return_value=None)
        mock_overdue.side_effect = RuntimeError('boom')
        db = AsyncMock()
        await run_equipment_notification_check_async(db)
        db.rollback.assert_awaited_once()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_check_overdue_skips_when_expected_none(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        assignment = MagicMock()
        assignment.expected_return_at = None
        assignment.checked_in_at = None

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([assignment]))
        await _check_overdue(db, org_id)
        mock_core.notifications.notify_org_admins_async.assert_not_called()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_check_maintenance_skips_when_next_date_none(
        self, mock_core: Any
    ) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        log = MagicMock()
        log.next_maintenance_at = None
        log.item_id = uuid4()
        item_ids = {log.item_id}

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([log]))

        with patch(
            'app.modules.equipment.notification_worker._get_equipment_item_ids',
            new_callable=AsyncMock,
            return_value=item_ids,
        ):
            await _check_maintenance(db, org_id, days=7)
            mock_core.notifications.notify_org_admins_async.assert_not_called()


@pytest.mark.unit
class TestNotificationDedup:
    """A second worker run must not insert duplicate notifications for
    the same natural key (org + reference + type + day)."""

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_warranty_skips_when_already_notified(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        from app.modules.equipment._schemas_dashboard import WarrantyAlert

        org_id = uuid4()
        alert = WarrantyAlert(
            item_id=uuid4(),
            item_name='Laptop',
            category_code='LAPTOP',
            serial_number='SN-001',
            warranty_until=date.today() + timedelta(days=15),
            days_remaining=15,
            assigned_to=None,
        )
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=True
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()
        with patch(
            'app.modules.equipment.dashboard_service.get_warranty_alerts',
            new_callable=AsyncMock,
            return_value=[alert],
        ):
            db = _mock_db()
            await _check_warranty_async(db, org_id, days=30)
            from app.core.contracts import NotificationDedupKey

            call = mock_core.notifications.exists_unread_by_meta_async.await_args
            assert call.args[:3] == (
                db,
                org_id,
                NotificationDedupKey(
                    meta_type='equipment_warranty',
                    ref_key='item_id',
                    ref_id=str(alert.item_id),
                ),
            )
            mock_core.notifications.notify_org_admins_async.assert_not_called()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_overdue_skips_when_already_notified(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        assignment = _mock_assignment(days_overdue=5, org_id=org_id)
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=True
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([assignment]))

        await _check_overdue(db, org_id)
        mock_core.notifications.exists_unread_by_meta_async.assert_awaited_once()
        mock_core.notifications.notify_org_admins_async.assert_not_called()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_maintenance_skips_when_already_notified(
        self, mock_core: Any
    ) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        log = _mock_maintenance_log(days_until=3)
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=True
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([log]))

        with patch(
            'app.modules.equipment.notification_worker._get_equipment_item_ids',
            new_callable=AsyncMock,
            return_value={log.item_id},
        ):
            await _check_maintenance(db, org_id, days=7)
            mock_core.notifications.exists_unread_by_meta_async.assert_awaited_once()
            mock_core.notifications.notify_org_admins_async.assert_not_called()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_overdue_notifies_when_not_yet_notified(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        assignment = _mock_assignment(days_overdue=5, org_id=org_id)
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=False
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock(return_value=[])
        mock_core.notifications.publish_async = AsyncMock()

        db = _mock_db()
        db.stream = AsyncMock(return_value=_mock_scalars_stream([assignment]))

        await _check_overdue(db, org_id)
        mock_core.notifications.notify_org_admins_async.assert_called_once()


@pytest.mark.unit
class TestGetWarningWindows:
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_uses_module_settings_when_present(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        mock_core.settings.get_async = AsyncMock(
            return_value={
                'warranty_warning_days': 60,
                'maintenance_warning_days': 14,
            }
        )
        warranty_days, maintenance_days = await _get_warning_windows(
            MagicMock(), uuid4()
        )
        assert warranty_days == 60
        assert maintenance_days == 14

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_falls_back_to_defaults_without_settings(
        self, mock_core: Any
    ) -> None:
        mock_core.settings.get_async = AsyncMock(return_value=None)
        warranty_days, maintenance_days = await _get_warning_windows(
            MagicMock(), uuid4()
        )
        assert warranty_days == WARRANTY_WARNING_DAYS
        assert maintenance_days == MAINTENANCE_WARNING_DAYS


@pytest.mark.unit
class TestCheckWarrantyAsync:
    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_sends_notification_for_alerts(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        from app.modules.equipment._schemas_dashboard import WarrantyAlert

        org_id = uuid4()
        alert = WarrantyAlert(
            item_id=uuid4(),
            item_name='Laptop',
            category_code='LAPTOP',
            serial_number='SN-001',
            warranty_until=date.today() + timedelta(days=15),
            days_remaining=15,
            assigned_to=None,
        )
        mock_core.notifications.exists_unread_by_meta_async = AsyncMock(
            return_value=False
        )
        mock_core.notifications.notify_org_admins_async = AsyncMock()
        mock_core.notifications.publish_async = AsyncMock()
        with patch(
            'app.modules.equipment.dashboard_service.get_warranty_alerts',
            new_callable=AsyncMock,
            return_value=[alert],
        ):
            db = _mock_db()
            await _check_warranty_async(db, org_id, days=30)
            mock_core.notifications.notify_org_admins_async.assert_called_once()
            mock_core.notifications.publish_async.assert_called_once()

    @patch('app.modules.equipment.notification_worker.core_api')
    async def test_no_alerts_no_notification(self, mock_core: Any) -> None:
        _org_clock(mock_core)
        org_id = uuid4()
        mock_core.notifications.notify_org_admins_async = MagicMock()
        with patch(
            'app.modules.equipment.dashboard_service.get_warranty_alerts',
            new_callable=AsyncMock,
            return_value=[],
        ):
            db = _mock_db()
            await _check_warranty_async(db, org_id, days=30)
            mock_core.notifications.notify_org_admins_async.assert_not_called()
