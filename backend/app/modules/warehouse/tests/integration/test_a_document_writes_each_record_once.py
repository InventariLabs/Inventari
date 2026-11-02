"""A document writes each of its records once.

The document executor and the stock service used to split one operation in
two: the door changed the record's number on its own, and the service
settled the quants and wrote the movement after it. The one-number stock
model (ADR-022) makes the service's ``post_movement_async`` the one
pass that changes the records it is handed, checks the grain it took from
and writes the movement — under the anchor locks it takes up front. Whatever
the pass looks like inside, an operation may state a record's number once: a
second write would apply the same quantity twice, and the drift the
reconciliation report reads is exactly what such a double write produces.

The counter listens on the engines the API runs on and counts the INSERT
and UPDATE statements that touch the record an operation is about, across
the document's create, confirm and complete. The receipt's new record is
created once (an INSERT, the door's identity work); every record an
operation changes is updated once.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.modules.warehouse.tests.integration._records import sow as _sow

pytestmark = pytest.mark.integration


class _RecordWriteWatch:
    """Counts the writes an operation states on one record, per dimension.

    A record's number and its shelf are two dimensions, written by two
    guarded services (the quantity through the items quantity path, the
    shelf through the move path) — a partial transfer legitimately touches
    both. What must never happen is the SAME dimension written twice: the
    quantity applied two times is the drift the reconciliation reads.
    """

    def __init__(self, record_id: UUID | None = None) -> None:
        self.record_id = record_id
        self.quantity_updates = 0
        self.shelf_updates = 0
        self.inserts = 0
        # Unfiltered counts, for a record that does not exist yet: a receipt
        # of a line the catalogue never heard of opens its record during the
        # completion, so there is no id to watch before the run.
        self.all_inserts = 0
        self.all_updates = 0

    def _names_the_record(self, parameters: Any) -> bool:
        values: Iterable[Any]
        if isinstance(parameters, dict):
            values = parameters.values()
        elif isinstance(parameters, (list, tuple)):
            # asyncpg runs positional parameters; the record's id is one of
            # the bound values, and which position it holds is the
            # statement's business, not the counter's.
            values = parameters
        else:
            return False
        return any(str(value) == str(self.record_id) for value in values)

    def on_statement(self, *args: Any) -> None:
        # The sync engine hands over (conn, cursor, statement, parameters,
        # context[, executemany]); the statement and the parameters keep
        # their places either way.
        statement, parameters = args[2], args[3]
        # A statement prefixed with a /* comment */ starts after the comment.
        statement = statement.lstrip()
        while statement.startswith('/*'):
            end = statement.find('*/')
            if end < 0:
                return
            statement = statement[end + 2 :].lstrip()
        head = statement[:19].upper()
        is_update = head.startswith('UPDATE ITEMS ')
        is_insert = head.startswith('INSERT INTO ITEMS ')
        if not is_update and not is_insert:
            return
        if is_update:
            self.all_updates += 1
        else:
            self.all_inserts += 1
        if self.record_id is None or not self._names_the_record(parameters):
            return
        if head.startswith('INSERT INTO ITEMS '):
            self.inserts += 1
        elif 'SET QUANTITY' in head or ' QUANTITY=' in statement[:80].upper():
            self.quantity_updates += 1
        elif 'STORAGE_LOCATION_ID' in statement[:80].upper():
            self.shelf_updates += 1
        else:
            # An items update that is neither dimension is still a write of
            # the record; it counts as a quantity write so it cannot hide.
            self.quantity_updates += 1


def _writes_of_record(
    client: Any,
    headers: dict[str, str],
    binds: list[Any],
    record_id: UUID,
    payload: dict[str, Any],
) -> _RecordWriteWatch:
    """Run one document through create, confirm and complete, counting writes."""
    watch = _RecordWriteWatch(record_id)
    for bind in binds:
        event.listen(bind, 'before_cursor_execute', watch.on_statement)
    try:
        created = client.post(
            '/api/v1/warehouse/documents', headers=headers, json=payload
        )
        assert created.status_code == 201, created.text
        doc_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == 200, completed.text
    finally:
        for bind in binds:
            event.remove(bind, 'before_cursor_execute', watch.on_statement)
    return watch


def _binds(db_session: Session, async_engine_fixture: AsyncEngine) -> list[Any]:
    # The Engine class, not the instances: a class-level listener is the one
    # level that sees every statement of the sync and the async engine alike.
    del db_session, async_engine_fixture
    return [Engine]


def _carded(
    h: ModuleTestHelper,
    db: Session,
    engine: AsyncEngine,
    org: Any,
    location_id: UUID,
    quantity: Decimal,
) -> Any:
    """A carded record whose stock went in through the items service."""
    template = h.create_template(org, name=f'once-{uuid4().hex[:6]}')
    return _sow(db, engine, org, template, location_id, quantity)


class TestReceiptWritesItsRecordOnce:
    def test_topping_a_record_up_writes_it_once(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        h = ModuleTestHelper(db_session)
        item = _carded(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_target_location.id,
            Decimal('5'),
        )

        watch = _writes_of_record(
            client,
            doc_auth_headers,
            _binds(db_session, async_engine_fixture),
            item.id,
            {
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        assert watch.quantity_updates == 1, (
            f'record quantity written {watch.quantity_updates} times'
        )
        assert watch.shelf_updates == 0
        assert watch.inserts == 0, 'the record was inserted again'

    def test_a_new_record_is_inserted_once(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'once-new-{uuid4().hex[:6]}')

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'product_template_id': str(template.id), 'expected_quantity': 3}
                ],
            },
        )
        assert created.status_code == 201, created.text
        doc_id = created.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == 200
        )

        watch = _RecordWriteWatch()
        for bind in _binds(db_session, async_engine_fixture):
            event.listen(bind, 'before_cursor_execute', watch.on_statement)
        try:
            completed = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )
            assert completed.status_code == 200, completed.text
        finally:
            for bind in _binds(db_session, async_engine_fixture):
                event.remove(bind, 'before_cursor_execute', watch.on_statement)

        # The record the line opened was inserted once, during this
        # completion, and nothing updated it afterwards.
        db_session.commit()
        from sqlalchemy import select as _select

        record = db_session.scalars(
            _select(Item).where(
                Item.organization_id == doc_org.id,
                Item.template_id == template.id,
                Item.is_deleted.is_(False),
            )
        ).first()
        assert record is not None, 'the receipt never opened its record'
        assert watch.all_inserts == 1, (
            f'items inserted {watch.all_inserts} times for one line'
        )
        assert watch.all_updates == 0, (
            f'items updated {watch.all_updates} times for one receipt'
        )


class TestTransferWritesItsRecordOnce:
    def test_a_full_line_moves_the_record_with_one_write(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        h = ModuleTestHelper(db_session)
        item = _carded(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location.id,
            Decimal('5'),
        )

        watch = _writes_of_record(
            client,
            doc_auth_headers,
            _binds(db_session, async_engine_fixture),
            item.id,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 5}],
            },
        )

        assert watch.shelf_updates == 1, (
            f'record shelf written {watch.shelf_updates} times'
        )
        assert watch.quantity_updates == 0
        assert watch.inserts == 0

    def test_a_partial_line_writes_the_record_once(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The record rides with the line's quantity; the rest stays as its
        own record. The moved record is written once, not once per dimension."""
        h = ModuleTestHelper(db_session)
        item = _carded(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location.id,
            Decimal('10'),
        )

        watch = _writes_of_record(
            client,
            doc_auth_headers,
            _binds(db_session, async_engine_fixture),
            item.id,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        assert watch.quantity_updates == 1, (
            f'record quantity written {watch.quantity_updates} times'
        )
        assert watch.shelf_updates == 1
        assert watch.inserts == 0


class TestCorrectionWritesItsRecordOnce:
    def test_a_correction_writes_the_record_once(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        h = ModuleTestHelper(db_session)
        item = _carded(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_target_location.id,
            Decimal('5'),
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 4}],
            },
        )
        assert created.status_code == 201, created.text
        original_id = created.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{original_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{original_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            ).status_code
            == 200
        )

        correction = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
            },
        )
        assert correction.status_code == 201, correction.text
        correction_id = correction.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{correction_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == 200
        )

        watch = _RecordWriteWatch(item.id)
        for bind in _binds(db_session, async_engine_fixture):
            event.listen(bind, 'before_cursor_execute', watch.on_statement)
        try:
            completed = client.patch(
                f'/api/v1/warehouse/documents/{correction_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            )
            assert completed.status_code == 200, completed.text
        finally:
            for bind in _binds(db_session, async_engine_fixture):
                event.remove(bind, 'before_cursor_execute', watch.on_statement)

        assert watch.quantity_updates == 1, (
            f'record quantity written {watch.quantity_updates} times'
        )
        assert watch.inserts == 0
