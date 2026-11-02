"""Two scans of one line both land — the line is re-read under its lock.

``execute_scan_async`` locked the document before touching the line, but the
line itself arrived from the caller, loaded before that lock was taken: two
scans of one product computed ``picked_quantity + scanned`` from the same
snapshot, and the second write quietly ate the first (5+3+3 ended at 6, not
11). The same window sat between a scan and an undo: the undo's 0 was
overwritten by a scan still adding onto the stale 5.

The repair re-reads the matched line under ``FOR UPDATE`` with
``populate_existing`` after the document lock — the identity map otherwise
hands back the object the caller loaded, stale by everything the lock waited
for. These tests park each racer on a lock a third connection holds, so the
interleaving is the one that lost the update, not one the scheduler chose.
Without the re-read each of the first three tests fails on its quantity
assertion and the guard test accepts a scan it should have refused.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse._picking_scan_ops import scan_pick_async
from app.modules.warehouse._picking_session_ops import undo_pick_async
from app.modules.warehouse._receiving_scan_ops import scan_receive_async
from app.modules.warehouse.models import DocumentLine, WmsPickLine
from app.modules.warehouse.tests.integration._records import sow as _sow

_PARK_TIMEOUT = 15.0  # seconds a racer gets to reach the lock it parks on


async def _wait_until_parked(engine: AsyncEngine, racers: int) -> None:
    """Return once ``racers`` backends of this database wait on a lock.

    A fixed sleep only guesses that each racer has reached its lock; on a
    loaded host it had not, and the interleaving the test is built around
    never happened. The database knows who is waiting, so ask it. Each poll
    is its own autocommit statement: ``pg_stat_activity`` is a snapshot cached
    for the length of a transaction, so a probe that kept one open would never
    see a racer that arrives after its first read.
    """
    probe_engine = engine.execution_options(isolation_level='AUTOCOMMIT')
    async with probe_engine.connect() as probe:
        deadline = asyncio.get_running_loop().time() + _PARK_TIMEOUT
        while True:
            waiting = await probe.scalar(
                text(
                    'SELECT count(*) FROM pg_stat_activity '
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            if waiting is not None and waiting >= racers:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f'{racers} racer(s) never parked on a lock')
            await asyncio.sleep(0.02)


async def _let_racers_finish(*tasks: asyncio.Task[Any]) -> None:
    """Wait out racers after their lock is released, swallowing their outcome.

    A failed wait must not leave a racer blocked on a lock: closing its
    session would hang, and the worker database's teardown with it.
    """
    await asyncio.gather(*tasks, return_exceptions=True)


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    source_location_id: uuid.UUID,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: int,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return cast(str, resp.json()['id'])


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': quantity}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return cast(str, resp.json()['id'])


def _start_picking(client: TestClient, headers: dict[str, str], doc_id: str) -> str:
    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    return cast(str, start.json()['id'])


def _start_receiving(client: TestClient, headers: dict[str, str], doc_id: str) -> str:
    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    return cast(str, start.json()['id'])


def _the_line(db: Session, session_id: str) -> WmsPickLine:
    line = db.scalars(
        select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
    ).first()
    assert line is not None
    return line


async def _two_parked_scans(
    engine: AsyncEngine,
    scan: Any,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    barcode: str,
    first_quantity: Decimal,
    second_quantity: Decimal,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two scans whose stale reads precede both writes, by construction.

    A blocker holds the line row, so the first scan parks before writing
    (its document lock already taken); the second then parks on that
    document lock, its lines read from the snapshot before the first scan
    committed anything. Releasing the blocker commits to the order the lost
    update lived in: first write, then a second scan still holding the old
    number.
    """
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as blocker, maker() as first, maker() as second:
        line_id = await blocker.scalar(
            select(WmsPickLine.id).where(WmsPickLine.session_id == session_id)
        )
        await blocker.execute(
            select(WmsPickLine).where(WmsPickLine.id == line_id).with_for_update()
        )

        tasks: list[asyncio.Task[Any]] = []
        try:
            first_task = asyncio.create_task(
                scan(first, session_id, org_id, barcode, first_quantity)
            )
            tasks.append(first_task)
            await _wait_until_parked(engine, 1)
            second_task = asyncio.create_task(
                scan(second, session_id, org_id, barcode, second_quantity)
            )
            tasks.append(second_task)
            await _wait_until_parked(engine, 2)
        except BaseException:
            await blocker.rollback()
            await _let_racers_finish(*tasks)
            raise

        await blocker.commit()
        first_answer = await first_task
        await first.commit()
        second_answer = await second_task
        await second.commit()
        return first_answer, second_answer


async def _committed_scan(
    engine: AsyncEngine,
    scan: Any,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
    barcode: str,
    quantity: Decimal,
) -> dict[str, Any]:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as db:
        answer = await scan(db, session_id, org_id, barcode, quantity)
        await db.commit()
        return cast(dict[str, Any], answer)


def _picking_scan(
    db: AsyncSession,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
    barcode: str,
    quantity: Decimal,
) -> Any:
    return scan_pick_async(db, session_id, org_id, barcode=barcode, quantity=quantity)


def _receiving_scan(
    db: AsyncSession,
    session_id: uuid.UUID,
    org_id: uuid.UUID,
    barcode: str,
    quantity: Decimal,
) -> Any:
    return scan_receive_async(
        db, session_id, org_id, barcode=barcode, quantity=quantity
    )


def _line_afterwards(db: Session, session_id: str) -> tuple[WmsPickLine, DocumentLine]:
    db.expire_all()
    line = _the_line(db, session_id)
    doc_line = db.scalars(
        select(DocumentLine).where(DocumentLine.id == line.document_line_id)
    ).first()
    assert doc_line is not None
    return line, doc_line


@pytest.mark.integration
class TestTwoPickingScansOfOneLine:
    def test_the_second_scan_adds_onto_the_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """5, then 3 parked on the first, then 3 more: the line holds 11.

        Without the locking re-read the parked scan computed 0+3 over the
        committed 5 and answered 3, and the line ended at 6.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
            quantity=12,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = _start_picking(client, doc_auth_headers, doc_id)
        barcode = doc_template.barcode
        assert barcode is not None
        db_session.commit()

        first_answer, second_answer = asyncio.run(
            _two_parked_scans(
                async_engine_fixture,
                _picking_scan,
                uuid.UUID(session_id),
                doc_org.id,
                barcode=barcode,
                first_quantity=Decimal('5'),
                second_quantity=Decimal('3'),
            )
        )
        assert first_answer['status'] == 'picked'
        assert second_answer['status'] == 'picked'

        third = asyncio.run(
            _committed_scan(
                async_engine_fixture,
                _picking_scan,
                uuid.UUID(session_id),
                doc_org.id,
                barcode,
                Decimal('3'),
            )
        )
        assert third['status'] == 'picked'

        line, doc_line = _line_afterwards(db_session, session_id)
        assert line.picked_quantity == Decimal('11')
        assert doc_line.done_quantity == Decimal('11')
        assert line.status == 'pending'


@pytest.mark.integration
class TestTwoReceivingScansOfOneLine:
    def test_the_second_scan_adds_onto_the_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Receiving answers to the same shared rule, so the same window.

        Without the locking re-read the parked scan computed 0+3 over the
        committed 5, and the line ended at 6 instead of 11.
        """
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=12,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = _start_receiving(client, doc_auth_headers, doc_id)
        barcode = doc_template.barcode
        assert barcode is not None
        db_session.commit()

        first_answer, second_answer = asyncio.run(
            _two_parked_scans(
                async_engine_fixture,
                _receiving_scan,
                uuid.UUID(session_id),
                doc_org.id,
                barcode=barcode,
                first_quantity=Decimal('5'),
                second_quantity=Decimal('3'),
            )
        )
        assert first_answer['status'] == 'received'
        assert second_answer['status'] == 'received'

        third = asyncio.run(
            _committed_scan(
                async_engine_fixture,
                _receiving_scan,
                uuid.UUID(session_id),
                doc_org.id,
                barcode,
                Decimal('3'),
            )
        )
        assert third['status'] == 'received'

        line, doc_line = _line_afterwards(db_session, session_id)
        assert line.picked_quantity == Decimal('11')
        assert doc_line.done_quantity == Decimal('11')
        assert line.status == 'pending'


@pytest.mark.integration
class TestTheOverQuantityGuardReadsTheLockedRow:
    def test_a_scan_the_competitor_already_covered_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Two scans of 5 against an expected 7: the second is over.

        The guard read the same stale snapshot the arithmetic did, so
        without the locking re-read the second scan answered 'picked' with
        0+5 and landed on a line the first had already filled.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
            quantity=7,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = _start_picking(client, doc_auth_headers, doc_id)
        barcode = doc_template.barcode
        assert barcode is not None
        db_session.commit()

        _, second_answer = asyncio.run(
            _two_parked_scans(
                async_engine_fixture,
                _picking_scan,
                uuid.UUID(session_id),
                doc_org.id,
                barcode=barcode,
                first_quantity=Decimal('5'),
                second_quantity=Decimal('5'),
            )
        )

        assert second_answer['status'] == 'over_quantity'
        line, _doc_line = _line_afterwards(db_session, session_id)
        assert line.picked_quantity == Decimal('5')


@pytest.mark.integration
class TestAScanParallelWithAnUndo:
    def test_neither_the_reset_nor_the_scan_is_lost(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The undo resets the line while a scan is parked behind it.

        The undo holds the line's own lock (it never takes the document's),
        so the scan re-read under that lock is what makes the reset visible:
        without it the scan wrote 5+3 over the committed 0 and the undo
        vanished. With it the line honestly holds the scan's 3.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
            quantity=12,
        )
        _confirm(client, doc_auth_headers, doc_id)
        session_id = _start_picking(client, doc_auth_headers, doc_id)
        barcode = doc_template.barcode
        assert barcode is not None
        line = _the_line(db_session, session_id)
        line_id = line.id
        db_session.commit()

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _undo_then_scan() -> None:
            async with maker() as undoing, maker() as scanning:
                await _committed_scan(
                    async_engine_fixture,
                    _picking_scan,
                    uuid.UUID(session_id),
                    doc_org.id,
                    barcode,
                    Decimal('5'),
                )

                # The undo returns once it holds the line lock with the reset
                # written, uncommitted — that is the state the scan parks on.
                await undo_pick_async(
                    undoing, uuid.UUID(session_id), doc_org.id, line_id
                )
                scan_task = asyncio.create_task(
                    scan_pick_async(
                        scanning,
                        uuid.UUID(session_id),
                        doc_org.id,
                        barcode=barcode,
                        quantity=Decimal('3'),
                    )
                )
                try:
                    await _wait_until_parked(async_engine_fixture, 1)
                except BaseException:
                    await undoing.rollback()
                    await _let_racers_finish(scan_task)
                    raise

                await undoing.commit()
                await scan_task
                await scanning.commit()

        asyncio.run(_undo_then_scan())

        line, doc_line = _line_afterwards(db_session, session_id)
        assert line.picked_quantity == Decimal('3')
        assert doc_line.done_quantity == Decimal('3')
        assert line.status == 'pending'


@pytest.mark.integration
class TestTheParkedProbeSeesLateArrivals:
    def test_a_racer_arriving_after_the_first_poll_is_noticed(
        self, async_engine_fixture: AsyncEngine, setup_test_db: None
    ) -> None:
        """The first poll finds nobody parked; the racer arrives afterwards.

        A probe that held one transaction open kept reading its first
        ``pg_stat_activity`` snapshot and timed out on a waiter that was
        really there.
        """

        async def _exercise() -> None:
            key = uuid.uuid4().int % (2**62)
            lock = text('SELECT pg_advisory_xact_lock(:key)')
            async with async_engine_fixture.connect() as holder:
                await holder.execute(lock, {'key': key})

                async def _late_waiter() -> None:
                    await asyncio.sleep(0.3)
                    async with async_engine_fixture.connect() as waiter:
                        await waiter.execute(lock, {'key': key})

                task = asyncio.create_task(_late_waiter())
                try:
                    await _wait_until_parked(async_engine_fixture, 1)
                finally:
                    await holder.rollback()
                    await task

        asyncio.run(_exercise())
