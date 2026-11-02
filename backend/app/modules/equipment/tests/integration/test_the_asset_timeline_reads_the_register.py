"""The asset timeline is one read, and a status change is on it.

The tab stitched its events in the browser from three reads and never
touched ``item_history``, so retiring an asset — or bringing it back —
left no trace anywhere the user could look. The endpoint composes the
timeline server-side; these tests walk a real lifecycle through the API
and read it back through the one response the tab consumes.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def tl_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Timeline Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'equipment'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def tl_user(real_async_db_session: AsyncSession, tl_org: Organization) -> User:
    user = User(
        email=f'tl_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Timeline User',
        organization_id=tl_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def tl_storage(
    real_async_db_session: AsyncSession,
    tl_org: Organization,
    tl_user: User,
) -> StorageLocation:
    storage_type = StorageType(
        name='Timeline Storage', type_code='TL_STORAGE', behavior_mode='NONE'
    )
    real_async_db_session.add(storage_type)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(storage_type)
    loc = StorageLocation(
        organization_id=tl_org.id,
        created_by=tl_user.id,
        storage_type_id=storage_type.id,
        name='Shelf One',
    )
    real_async_db_session.add(loc)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(loc)
    return loc


@pytest.fixture
async def tl_category(real_async_db_session: AsyncSession) -> Category:
    cat = Category(
        name='Laptop',
        code='LAPTOP',
        context_tag='equipment',
        organization_id=None,
        field_definitions=[
            {
                'key': 'equipment_status',
                'type': 'select',
                'label': 'Status',
                'is_system': True,
            },
        ],
    )
    real_async_db_session.add(cat)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(cat)
    return cat


@pytest.fixture
async def tl_item(
    real_async_db_session: AsyncSession,
    tl_org: Organization,
    tl_storage: StorageLocation,
    tl_category: Category,
) -> Item:
    item = Item(
        name='ThinkPad T480',
        organization_id=tl_org.id,
        storage_location_id=tl_storage.id,
        category_id=tl_category.id,
        quantity=1,
        meta_data={
            'equipment': {'serial_number': 'SN-TL', 'equipment_status': 'AVAILABLE'}
        },
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


async def _timeline(
    client: AsyncClient, user: User, item_id: UUID
) -> list[dict[str, Any]]:
    response = await client.get(
        f'/api/v1/equipment/assets/{item_id}/timeline', headers=_auth(user)
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    events: list[dict[str, Any]] = response.json()['events']
    return events


@pytest.mark.integration
@pytest.mark.asyncio
class TestAssetTimeline:
    async def test_a_retirement_and_its_reversal_are_on_the_timeline(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        """Retire the asset, bring it back: both transitions read back."""
        await real_async_client.post(
            f'/api/v1/equipment/items/{tl_item.id}/retire', headers=_auth(tl_user)
        )
        # The app's own way back: the bulk status edit writes the same
        # STATUS_CHANGED history row the retirement does.
        restore = await real_async_client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=_auth(tl_user),
            json={
                'item_ids': [str(tl_item.id)],
                'action': 'change_status',
                'data': {'status': 'AVAILABLE'},
            },
        )
        assert restore.status_code == 200, restore.text

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        changes = [e for e in events if e['kind'] == 'status_changed']
        assert len(changes) == 2
        assert changes[0]['new_status'] == 'AVAILABLE'
        assert changes[0]['old_status'] == 'RETIRED'
        assert changes[1]['old_status'] == 'AVAILABLE'
        assert changes[1]['new_status'] == 'RETIRED'
        assert changes[0]['date'] >= changes[1]['date']

    async def test_a_handover_names_both_sides_of_it(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        headers = _auth(tl_user)
        checkout = await real_async_client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={
                'item_id': str(tl_item.id),
                'assigned_to_name': 'Anna Nowak',
                'assigned_to_email': 'anna@example.com',
                'checkout_notes': 'charger included',
            },
        )
        assert checkout.status_code == 201, checkout.text
        assignment = checkout.json()

        checkin = await real_async_client.post(
            f'/api/v1/equipment/assignments/{assignment["id"]}/checkin',
            headers=headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert checkin.status_code == 200, checkin.text

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        kinds = [e['kind'] for e in events]
        assert 'checkout' in kinds and 'checkin' in kinds

        out = next(e for e in events if e['kind'] == 'checkout')
        assert out['holder_name'] == 'Anna Nowak'
        assert out['holder_kind'] == 'person'
        assert out['holder_email'] == 'anna@example.com'
        assert out['notes'] == 'charger included'

        back = next(e for e in events if e['kind'] == 'checkin')
        assert back['holder_name'] == 'Anna Nowak'
        assert back['holder_kind'] == 'person'
        assert back['operator_name'] is not None
        assert back['condition'] == 'GOOD'

        # One source row stands for two events here — the assignment is
        # both its checkout and its check-in — so event identity, not row
        # identity, has to keep the interface's keys apart.
        ids = [e['id'] for e in events if e['id']]
        assert len(set(ids)) == len(ids)

    async def test_a_deployment_names_the_place_it_stands_in(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_org: Organization,
        tl_user: User,
        tl_storage: StorageLocation,
        tl_item: Item,
    ) -> None:
        """A deployment has no person to name. The card carries the place
        and says it is one — the reader picks its wording from the kind."""
        rack = StorageLocation(
            organization_id=tl_org.id,
            created_by=tl_user.id,
            storage_type_id=tl_storage.storage_type_id,
            name='Rack B',
        )
        real_async_db_session.add(rack)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(rack)

        checkout = await real_async_client.post(
            '/api/v1/equipment/assignments',
            headers=_auth(tl_user),
            json={
                'item_id': str(tl_item.id),
                'assigned_to_name': '',
                'checkout_location_id': str(rack.id),
            },
        )
        assert checkout.status_code == 201, checkout.text

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        out = next(e for e in events if e['kind'] == 'checkout')
        assert out['holder_name'] == 'Rack B'
        assert out['holder_kind'] == 'location'
        assert out['holder_email'] is None

    async def test_a_repair_keeps_its_cost_on_the_timeline(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        from datetime import date

        log = await real_async_client.post(
            '/api/v1/equipment/maintenance',
            headers=_auth(tl_user),
            json={
                'item_id': str(tl_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Hinge replacement',
                'cost': '120.50',
                'currency': 'PLN',
                'performed_at': date.today().isoformat(),
            },
        )
        assert log.status_code == 201, log.text

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        repairs = [e for e in events if e['kind'] == 'maintenance']
        assert len(repairs) == 1
        assert repairs[0]['title'] == 'Hinge replacement'
        assert repairs[0]['maintenance_type'] == 'REPAIR'
        assert repairs[0]['cost'] == '120.50'

    async def test_the_timeline_sorts_newest_first_across_kinds(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        from datetime import UTC, datetime, timedelta

        await real_async_client.post(
            '/api/v1/equipment/maintenance',
            headers=_auth(tl_user),
            json={
                'item_id': str(tl_item.id),
                'maintenance_type': 'INSPECTION',
                'title': 'Annual check',
                'performed_at': (datetime.now(UTC) - timedelta(days=30))
                .date()
                .isoformat(),
            },
        )
        await real_async_client.post(
            f'/api/v1/equipment/items/{tl_item.id}/retire', headers=_auth(tl_user)
        )

        events = await _timeline(real_async_client, tl_user, tl_item.id)

        # A DATE-only maintenance day counts as the whole of that day, so
        # ordering is read on moments, not on strings: "2026-09-05" must
        # not sink below a timestamp it actually outlasts.
        def moment(raw: str) -> tuple[int, ...]:
            if len(raw) == 10:
                return (*[int(x) for x in raw.split('-')], 23, 59, 59)
            from datetime import datetime as dt

            return dt.fromisoformat(raw.replace('Z', '+00:00')).timetuple()

        keys = [moment(e['date']) for e in events]
        assert keys == sorted(keys, reverse=True)
        assert events[0]['kind'] == 'status_changed'

    async def test_a_same_day_repair_sorts_by_when_it_was_recorded(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        """A later status change comes after a repair recorded today."""
        from datetime import date

        log = await real_async_client.post(
            '/api/v1/equipment/maintenance',
            headers=_auth(tl_user),
            json={
                'item_id': str(tl_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Same-day repair',
                'performed_at': date.today().isoformat(),
            },
        )
        assert log.status_code == 201, log.text
        await real_async_client.post(
            f'/api/v1/equipment/items/{tl_item.id}/retire', headers=_auth(tl_user)
        )

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        kinds = [e['kind'] for e in events]
        assert kinds.index('status_changed') < kinds.index('maintenance')

    async def test_local_days_sort_before_creation_time(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_org: Organization,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.modules.equipment.models import EquipmentMaintenanceLog

        tl_org.timezone = 'Europe/Warsaw'
        await real_async_db_session.commit()
        for title, day in [
            ('Yesterday', '2026-10-29'),
            ('First today', '2026-10-30'),
            ('Second today', '2026-10-30'),
        ]:
            response = await real_async_client.post(
                '/api/v1/equipment/maintenance',
                headers=_auth(tl_user),
                json={
                    'item_id': str(tl_item.id),
                    'maintenance_type': 'INSPECTION',
                    'title': title,
                    'performed_at': day,
                },
            )
            assert response.status_code == 201, response.text
            log = await real_async_db_session.scalar(
                select(EquipmentMaintenanceLog).where(
                    EquipmentMaintenanceLog.id == UUID(response.json()['id'])
                )
            )
            assert log is not None
            log.created_at = datetime(
                2026, 10, 29, 23, 23 if title != 'Second today' else 24, tzinfo=UTC
            )
        await real_async_db_session.commit()

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        assert [e['title'] for e in events if e['kind'] == 'maintenance'] == [
            'Second today',
            'First today',
            'Yesterday',
        ]

    async def test_the_created_entry_opens_the_feed_with_identity(
        self,
        real_async_client: AsyncClient,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        events = await _timeline(real_async_client, tl_user, tl_item.id)
        created = [e for e in events if e['kind'] == 'created']
        assert len(created) == 1
        assert created[0]['id'] == f'created:{tl_item.id}'
        # Every entry carries the identity of the row it came from.
        assert all(e.get('id') for e in events)

    async def test_a_history_row_of_an_unnamed_kind_is_not_a_status_change(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item: Item,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The mapping names what a history row is; the query filter is an
        optimization, not the definition. Every row once arrived as a
        ``status_changed`` card with empty transitions, held out of the
        answer only by the filter the query carries — so the first person
        to widen that filter produced 200 lying cards and no test noticed.
        Widening it here on purpose: a row whose action the timeline
        cannot name is skipped, not dressed up."""
        import sys

        from app.models.item_history import ItemHistory

        # The module registry keeps its own copy of the module in
        # sys.modules, so the copy this test file imports is not always the
        # one the request executes. Patch every loaded copy of the module.
        timeline_copies = [
            module
            for name, module in sys.modules.items()
            if name.endswith('equipment._asset_timeline') and module is not None
        ]
        # The patch below is only as wide as this list: if the name match
        # ever stops hitting any copy (a rename of the module or of this
        # suffix), an empty list patches nothing and this test goes green
        # while having touched nothing the request executes.
        assert timeline_copies, (
            'no sys.modules copy whose name ends with '
            '"equipment._asset_timeline" — the monkeypatch below would '
            'reach nothing'
        )

        row = ItemHistory(
            organization_id=tl_item.organization_id,
            item_id=tl_item.id,
            user_id=tl_user.id,
            action='UPDATED',
            changes={'name': {'old': 'ThinkPad T480', 'new': 'ThinkPad T490'}},
        )
        real_async_db_session.add(row)
        await real_async_db_session.commit()

        for timeline_module in timeline_copies:
            monkeypatch.setattr(
                timeline_module,
                '_TIMELINE_ACTIONS',
                ('STATUS_CHANGED', 'UPDATED'),
            )

        with caplog.at_level('WARNING'):
            events = await _timeline(real_async_client, tl_user, tl_item.id)

        assert f'status_changed:{row.id}' not in [e['id'] for e in events]
        named = [e for e in events if e['kind'] == 'status_changed']
        assert all(e['old_status'] or e['new_status'] for e in named)
        # The skip is not silent: a kind added tomorrow would otherwise
        # vanish from the screen as quietly as it used to lie on it.
        skips = [r for r in caplog.records if 'cannot name' in r.getMessage()]
        assert len(skips) == 1
        assert "{'UPDATED': 1}" in skips[0].getMessage()

    async def test_an_unknown_previous_status_is_no_status(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item: Item,
    ) -> None:
        """The metadata reader wrote ``UNKNOWN`` where an asset had no
        status, and the register kept it as a status name: the card read
        “UNKNOWN → Wycofany” — an untranslated sentinel standing where a
        state belongs, on a screen whose every other word is Polish. The
        machine itself already treats UNKNOWN as absence
        (``validate_transition`` walks past it); the timeline now speaks
        the same language — no previous status, and the reader gets the
        dash the interface keeps for “nothing”, not a word it cannot
        translate. A real previous status stays untouched."""
        from app.models.item_history import ItemHistory

        sentinel_row = ItemHistory(
            organization_id=tl_item.organization_id,
            item_id=tl_item.id,
            user_id=tl_user.id,
            action='STATUS_CHANGED',
            changes={'old_status': 'UNKNOWN', 'new_status': 'RETIRED'},
        )
        real_row = ItemHistory(
            organization_id=tl_item.organization_id,
            item_id=tl_item.id,
            user_id=tl_user.id,
            action='STATUS_CHANGED',
            changes={'old_status': 'AVAILABLE', 'new_status': 'MAINTENANCE'},
        )
        real_async_db_session.add_all([sentinel_row, real_row])
        await real_async_db_session.commit()

        events = await _timeline(real_async_client, tl_user, tl_item.id)
        ids = {e['id']: e for e in events}

        sentinel = ids[f'status_changed:{sentinel_row.id}']
        assert sentinel['old_status'] is None
        assert sentinel['new_status'] == 'RETIRED'

        real = ids[f'status_changed:{real_row.id}']
        assert real['old_status'] == 'AVAILABLE'
        assert real['new_status'] == 'MAINTENANCE'


@pytest.fixture
async def tl_item_no_status(
    real_async_db_session: AsyncSession,
    tl_org: Organization,
    tl_storage: StorageLocation,
    tl_category: Category,
) -> Item:
    """An asset from before the status interceptor: no equipment_status at all."""
    item = Item(
        name='Desk lamp',
        organization_id=tl_org.id,
        storage_location_id=tl_storage.id,
        category_id=tl_category.id,
        quantity=1,
        meta_data={'equipment': {'serial_number': 'SN-NOSTATUS'}},
    )
    real_async_db_session.add(item)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(item)
    return item


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheRegisterNeverWritesTheSentinel:
    """The writers record null where there was no status.

    The timeline already reads UNKNOWN as absence, but the register and
    the journal carried the literal — and every other reader of those two
    tables printed it verbatim. Normalizing at the write closes the class
    for rows not yet written; the readers carry the rows that exist.
    """

    async def _status_rows(
        self,
        db: AsyncSession,
        item_id: UUID,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.models.item_history import ItemHistory

        rows = (
            await db.scalars(
                select(ItemHistory).where(
                    ItemHistory.item_id == item_id,
                    ItemHistory.action == 'STATUS_CHANGED',
                )
            )
        ).all()
        # a STATUS_CHANGED row always carries its changes; the guard keeps
        # the row count honest if that assumption ever breaks
        return [dict(row.changes) for row in rows if row.changes is not None]

    async def test_a_retirement_records_null_not_unknown(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item_no_status: Item,
    ) -> None:
        response = await real_async_client.post(
            f'/api/v1/equipment/items/{tl_item_no_status.id}/retire',
            headers=_auth(tl_user),
        )
        assert response.status_code == 204, response.text

        changes = await self._status_rows(real_async_db_session, tl_item_no_status.id)
        assert changes, 'retirement wrote no STATUS_CHANGED row'
        assert changes[-1] == {'old_status': None, 'new_status': 'RETIRED'}

    async def test_a_maintenance_log_leaves_missing_status_unchanged(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item_no_status: Item,
    ) -> None:
        from datetime import date

        response = await real_async_client.post(
            '/api/v1/equipment/maintenance',
            headers=_auth(tl_user),
            json={
                'item_id': str(tl_item_no_status.id),
                'maintenance_type': 'REPAIR',
                'title': 'Hinge replacement',
                'performed_at': date.today().isoformat(),
            },
        )
        assert response.status_code in (200, 201), response.text

        changes = await self._status_rows(real_async_db_session, tl_item_no_status.id)
        assert changes == []

    async def test_a_bulk_edit_records_null_not_unknown(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item_no_status: Item,
    ) -> None:
        response = await real_async_client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=_auth(tl_user),
            json={
                'item_ids': [str(tl_item_no_status.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )
        assert response.status_code == 200, response.text

        changes = await self._status_rows(real_async_db_session, tl_item_no_status.id)
        assert changes, 'bulk edit wrote no STATUS_CHANGED row'
        assert changes[-1] == {'old_status': None, 'new_status': 'MAINTENANCE'}

    async def test_the_journal_snapshot_records_null_not_unknown(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        tl_user: User,
        tl_item_no_status: Item,
    ) -> None:
        from sqlalchemy import select

        from app.models.audit_log import AuditLog

        response = await real_async_client.post(
            f'/api/v1/equipment/items/{tl_item_no_status.id}/retire',
            headers=_auth(tl_user),
        )
        assert response.status_code == 204, response.text

        rows = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.target_id == tl_item_no_status.id,
                    AuditLog.target_type == 'equipment_asset',
                    AuditLog.action == 'UPDATE',
                )
            )
        ).all()
        assert rows, 'retirement wrote no journal row'
        snapshot = rows[-1].snapshot
        assert snapshot is not None
        before = snapshot['before']['equipment_status']
        assert before is None
