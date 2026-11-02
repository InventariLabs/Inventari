"""Stock take writes reach the organization log.

Finalising a count was journaled — opening, editing, counting, deleting
one and keeping the schedules that fire counts were not. A manager who
deleted a count, or edited a schedule that decides what gets counted
every month, left the log silent; "who removed this" had no answer.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.storage_location import StorageLocation


def _entries(db_session: Session, org_id: Any, target_id: str) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_id == target_id,
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


def _open_count(
    client: TestClient,
    auth_headers: dict[str, str],
    storage: StorageLocation,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/stock-takes',
        headers=auth_headers,
        json={'name': name, 'location_id': str(storage.id)},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return dict(response.json())


def _first_item_id(
    client: TestClient, headers: dict[str, str], stock_take_id: str
) -> str:
    items = client.get(
        f'/api/v1/stock-takes/{stock_take_id}/items', headers=headers
    ).json()['items']
    assert items, 'the opened count holds no rows to count'
    return str(items[0]['id'])


def _org_of(storage: StorageLocation) -> Any:
    return storage.organization_id


@pytest.mark.integration
class TestStockTakeWritesReachTheLog:
    def test_creating_a_count_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        name = f'JRNL open {uuid4().hex[:6]}'
        stock_take = _open_count(client, auth_headers, test_storage_location, name)

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        creates = [entry for entry in entries if entry.action == 'CREATE']
        assert creates, 'opening the count left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['name'] == name
        assert snapshot['items_count'] == stock_take['items_count']
        assert creates[0].user_id is not None

    def test_counting_a_row_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        stock_take = _open_count(
            client, auth_headers, test_storage_location, f'JRNL count {uuid4().hex[:6]}'
        )
        item_id = _first_item_id(client, auth_headers, stock_take['id'])

        counted = client.patch(
            f'/api/v1/stock-takes/{stock_take["id"]}/items/{item_id}/count',
            headers=auth_headers,
            json={'counted_quantity': 3},
        )
        assert counted.status_code == status.HTTP_200_OK, counted.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE'
            and (entry.snapshot or {}).get('counted_quantity')
        ]
        assert updates, 'counting the row left no entry in the log'
        snapshot = updates[0].snapshot or {}
        assert snapshot['counted_quantity'] == '3'
        assert snapshot['old_counted_quantity'] in (None, 'None')

    def test_bulk_counting_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        stock_take = _open_count(
            client, auth_headers, test_storage_location, f'JRNL bulk {uuid4().hex[:6]}'
        )
        item_id = _first_item_id(client, auth_headers, stock_take['id'])

        counted = client.patch(
            f'/api/v1/stock-takes/{stock_take["id"]}/items/bulk-count',
            headers=auth_headers,
            json=[{'item_id': item_id, 'counted_quantity': 2}],
        )
        assert counted.status_code == status.HTTP_200_OK, counted.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE' and (entry.snapshot or {}).get('bulk')
        ]
        assert updates, 'bulk counting left no entry in the log'
        assert (updates[0].snapshot or {})['counted_rows'] == 1

    def test_a_surplus_row_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        stock_take = _open_count(
            client,
            auth_headers,
            test_storage_location,
            f'JRNL surplus {uuid4().hex[:6]}',
        )
        # A surplus is an item the snapshot did not expect: the record is
        # created after the count opened, so it is genuinely not in it.
        late_item = Item(
            organization_id=test_storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            name='Late arrival',
            quantity=0,
        )
        db_session.add(late_item)
        db_session.commit()

        added = client.post(
            f'/api/v1/stock-takes/{stock_take["id"]}/items',
            headers=auth_headers,
            json={'item_id': str(late_item.id), 'counted_quantity': 1},
        )
        assert added.status_code == status.HTTP_201_CREATED, added.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        creates = [
            entry
            for entry in entries
            if entry.action == 'CREATE' and (entry.snapshot or {}).get('surplus')
        ]
        assert creates, 'adding the surplus row left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['item_id'] == str(late_item.id)
        assert snapshot['counted_quantity'] == '1'

    def test_requesting_a_recount_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        stock_take = _open_count(
            client,
            auth_headers,
            test_storage_location,
            f'JRNL recount {uuid4().hex[:6]}',
        )
        item_id = _first_item_id(client, auth_headers, stock_take['id'])

        recounted = client.post(
            f'/api/v1/stock-takes/{stock_take["id"]}/items/{item_id}/recount',
            headers=auth_headers,
        )
        assert recounted.status_code == status.HTTP_200_OK, recounted.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE'
            and (entry.snapshot or {}).get('recount_requested')
        ]
        assert updates, 'requesting the recount left no entry in the log'

    def test_editing_a_count_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        stock_take = _open_count(
            client, auth_headers, test_storage_location, f'JRNL edit {uuid4().hex[:6]}'
        )

        edited = client.put(
            f'/api/v1/stock-takes/{stock_take["id"]}',
            headers=auth_headers,
            json={'name': 'JRNL renamed'},
        )
        assert edited.status_code == status.HTTP_200_OK, edited.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE'
            and 'name' in (entry.snapshot or {}).get('fields', [])
        ]
        assert updates, 'editing the count left no entry in the log'

    def test_a_status_change_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        stock_take = _open_count(
            client,
            auth_headers,
            test_storage_location,
            f'JRNL status {uuid4().hex[:6]}',
        )

        changed = client.patch(
            f'/api/v1/stock-takes/{stock_take["id"]}/status',
            headers=auth_headers,
            json={'status': 'cancelled'},
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE'
            and (entry.snapshot or {}).get('new_status') == 'cancelled'
        ]
        assert updates, 'the status change left no entry in the log'
        assert (updates[0].snapshot or {})['old_status'] == 'in_progress'

    def test_deleting_a_count_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        stock_take = _open_count(
            client,
            auth_headers,
            test_storage_location,
            f'JRNL delete {uuid4().hex[:6]}',
        )

        deleted = client.delete(
            f'/api/v1/stock-takes/{stock_take["id"]}', headers=auth_headers
        )
        assert deleted.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        ), deleted.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        deletes = [entry for entry in entries if entry.action == 'SOFT_DELETE']
        assert deletes, 'deleting the count left no entry in the log'
        assert (deletes[0].snapshot or {})['name'] == stock_take['name']
        assert deletes[0].user_id is not None


@pytest.mark.integration
class TestCycleCountSchedulesReachTheLog:
    def _schedule(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        storage: StorageLocation,
        name: str,
    ) -> dict[str, Any]:
        created = client.post(
            '/api/v1/stock-takes/cycle-count-schedules',
            headers=auth_headers,
            json={
                'name': name,
                'frequency': 'monthly',
                'scope': 'all',
                'scope_filter': {'storage_location_id': str(storage.id)},
            },
        )
        assert created.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), created.text
        return dict(created.json())

    def test_creating_a_schedule_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        name = f'JRNL schedule {uuid4().hex[:6]}'
        schedule = self._schedule(client, auth_headers, test_storage_location, name)

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), schedule['id'])
        creates = [
            entry
            for entry in entries
            if entry.action == 'CREATE'
            and entry.target_type == 'cycle_count_schedule'
            and (entry.snapshot or {}).get('name') == name
        ]
        assert creates, 'creating the schedule left no entry in the log'

    def test_editing_a_schedule_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        schedule = self._schedule(
            client, auth_headers, test_storage_location, f'JRNL sched {uuid4().hex[:6]}'
        )

        edited = client.patch(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule["id"]}',
            headers=auth_headers,
            json={'sample_size': 5},
        )
        assert edited.status_code == status.HTTP_200_OK, edited.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), schedule['id'])
        updates = [
            entry
            for entry in entries
            if entry.action == 'UPDATE'
            and 'sample_size' in (entry.snapshot or {}).get('fields', [])
        ]
        assert updates, 'editing the schedule left no entry in the log'

    def test_deleting_a_schedule_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
    ) -> None:
        name = f'JRNL sched del {uuid4().hex[:6]}'
        schedule = self._schedule(client, auth_headers, test_storage_location, name)

        deleted = client.delete(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule["id"]}',
            headers=auth_headers,
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.text

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), schedule['id'])
        deletes = [entry for entry in entries if entry.action == 'HARD_DELETE']
        assert deletes, 'deleting the schedule left no entry in the log'
        assert (deletes[0].snapshot or {})['name'] == name
        assert deletes[0].target_type == 'cycle_count_schedule'

    def test_a_scheduled_run_reaches_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
    ) -> None:
        name = f'JRNL sched run {uuid4().hex[:6]}'
        schedule = self._schedule(client, auth_headers, test_storage_location, name)

        run = client.post(
            f'/api/v1/stock-takes/cycle-count-schedules/{schedule["id"]}/run',
            headers=auth_headers,
        )
        assert run.status_code == status.HTTP_201_CREATED, run.text
        stock_take = dict(run.json())

        db_session.expire_all()
        entries = _entries(db_session, _org_of(test_storage_location), stock_take['id'])
        creates = [entry for entry in entries if entry.action == 'CREATE']
        assert creates, 'the scheduled run left no entry in the log'
        snapshot = creates[0].snapshot or {}
        assert snapshot['name'] == stock_take['name']
        assert snapshot['generated_from_schedule'] == name
