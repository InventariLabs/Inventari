"""Fifty people working the stock at once leave it whole.

Stock changes through a handful of doors: an issue confirmed (it holds what
it will take), cancelled (it lets go) or completed (it takes it, in the
product's removal order); a delivery; part of a record carried to another
shelf; an issue of two products whose lines come in either order. Each door
locks what it will write before it reads what is free, and that lock is all
that stands between two people and a shelf sold twice.

A test that sends one request at a time cannot see whether the lock holds:
the only interleaving it ever produces is the sequential one. Here fifty
sessions, each on a connection of its own, go through the doors at once,
and what follows must hold for any order the scheduler picks:

- the drain: sixty records of five, half the people issuing five at a time
  and half holding five for an order, until the shelf refuses them. Exactly
  sixty confirmations go through — a sixty-first means two people were
  promised the same five — and every issue that was confirmed completes;
- nothing committed is ever below zero, and no group ever holds more for
  orders than it has on the shelf. A watcher on its own connection reads
  that every few milliseconds while the others work;
- the ledger accounts for every unit: for each product, shelf and batch,
  what stood before plus the movements written equals what stands after. A
  lost update shows up here even when nothing went negative. The watcher
  checks the same sum while the others work, in one snapshot each time
  (``REPEATABLE READ``): an operation whose record and movement landed in
  two commits would add up at the end and still leave a moment that does
  not;
- no deadlock, counted rather than retried, and no error that is not the
  door saying no.

The test reads the records and the records' view, never the quant table, and
goes only through doors a person uses, so how the doors lock may change
underneath without the test changing.

A green run means something only if the same run without the locks goes
red: the stock lock replaced by nothing and ``FOR UPDATE`` taken off every
query, the probe must report damage. That check is run by hand against
``_run`` and not kept in the suite, because whether an unprotected run breaks
in a given second is up to the scheduler.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypeVar

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse._document_workflow_crud import create_document
from app.modules.warehouse._document_workflow_transitions import (
    cancel_document,
    complete_document,
    confirm_document,
)
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.schemas import (
    DocumentComplete,
    DocumentCreate,
    DocumentLineCreate,
)
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.slow]

_WORKERS = 50
_CHAOS_OPS = 12
_SEED = 7
_DRAIN_RECORDS = 60
_DRAIN_EACH = Decimal('5')

_T = TypeVar('_T')
_Door = Callable[[AsyncSession], Awaitable[_T]]

_DEADLOCK = '40P01'
_LOCK_TIMEOUT = '55P03'


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


@dataclass
class _Warehouse:
    org_id: uuid.UUID
    user_id: uuid.UUID
    shelves: tuple[uuid.UUID, uuid.UUID]
    #: FEFO, three batches on each shelf.
    yoghurt: uuid.UUID
    #: FIFO; the drain empties it on the first shelf.
    rice: uuid.UUID
    #: FIFO, the second line of a two-product issue.
    flour: uuid.UUID
    batches: dict[str, date]


async def _warehouse(db: AsyncSession) -> _Warehouse:
    org = Organization(
        name=f'Many hands {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'hands_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelves: list[uuid.UUID] = []
    for name in ('Home shelf', 'Overflow shelf'):
        location = StorageLocation(
            organization_id=org.id, created_by=user.id, name=name
        )
        db.add(location)
        await db.flush()
        shelves.append(location.id)
    home, overflow = shelves

    def card(name: str, strategy: str) -> ProductTemplate:
        template = ProductTemplate(
            organization_id=org.id,
            name=f'{name} {uuid.uuid4().hex[:6]}',
            sku=f'{name}-{uuid.uuid4().hex[:8]}',
            removal_strategy=strategy,
        )
        db.add(template)
        return template

    yoghurt, rice, flour = (
        card('Yoghurt', 'FEFO'),
        card('Rice', 'FIFO'),
        card('Flour', 'FIFO'),
    )
    await db.flush()

    today = date.today()
    batches = {f'Y-{n}': today + timedelta(days=10 * n) for n in (1, 2, 3)}
    for batch, expires in batches.items():
        lot_id = await core_api.stock.get_or_create_lot_async(
            db, org.id, yoghurt.id, batch, expiry_date=expires
        )
        for shelf in shelves:
            await put_on_shelf(
                db, user, yoghurt, shelf, 20, lot_id=lot_id, expiry_date=expires
            )
    for _ in range(_DRAIN_RECORDS):
        await put_on_shelf(db, user, rice, home, _DRAIN_EACH)
    for shelf, template, count in (
        (overflow, rice, 4),
        (home, flour, 4),
        (overflow, flour, 4),
    ):
        for _ in range(count):
            await put_on_shelf(db, user, template, shelf, 10)
    # Every door reads the document profile; made here so the fifty do not
    # race on creating it instead.
    await get_or_create_profile(db, org.id)
    await db.commit()
    return _Warehouse(
        org_id=org.id,
        user_id=user.id,
        shelves=(home, overflow),
        yoghurt=yoghurt.id,
        rice=rice.id,
        flour=flour.id,
        batches=batches,
    )


def _sqlstate(exc: BaseException) -> str | None:
    seen: BaseException | None = exc
    while seen is not None:
        for name in ('sqlstate', 'pgcode'):
            code = getattr(seen, name, None)
            if isinstance(code, str):
                return code
        seen = getattr(seen, 'orig', None) or seen.__cause__
    return None


@dataclass
class _Tally:
    ok: Counter[str] = field(default_factory=Counter)
    refused: Counter[str] = field(default_factory=Counter)
    #: What the doors said when they said no, so a run refused for the wrong
    #: reason reads as that and not as a quiet shelf.
    reasons: Counter[str] = field(default_factory=Counter)
    deadlocks: int = 0
    timeouts: int = 0
    #: Which door waited too long, and on which statement, so a timeout reads
    #: as the lock it queued for.
    waited: Counter[str] = field(default_factory=Counter)
    #: Anything that is not the door saying no — a constraint the database
    #: had to enforce because the code did not, an exception nobody expected.
    errors: list[str] = field(default_factory=list)


class _Hands:
    """The doors, each one attempt in a session of its own."""

    def __init__(self, engine: AsyncEngine, warehouse: _Warehouse) -> None:
        self.factory = async_sessionmaker(engine, class_=AsyncSession)
        self.wh = warehouse
        self.tally = _Tally()

    async def attempt(self, kind: str, door: _Door[_T]) -> _T | None:
        """What the door gave back, or None when it did not go through."""
        async with self.factory() as session:
            try:
                result = await door(session)
                # The services leave the commit to the request; this is the request.
                await session.commit()
            except DBAPIError as exc:
                await session.rollback()
                code = _sqlstate(exc)
                if code == _DEADLOCK:
                    self.tally.deadlocks += 1
                elif code == _LOCK_TIMEOUT:
                    self.tally.timeouts += 1
                    statement = ' '.join(str(exc.statement).split())[:70]
                    self.tally.waited[f'{kind}: {statement}'] += 1
                else:
                    self.tally.errors.append(f'{kind}: {code} {exc}'[:300])
                return None
            except ValidationError as exc:
                # A payload the test built wrong is the test's fault, not a refusal.
                await session.rollback()
                self.tally.errors.append(f'{kind}: {exc}'[:300])
                return None
            except (ValueError, LookupError) as exc:
                # The door said no: not enough free, a record that moved on.
                await session.rollback()
                self.tally.refused[kind] += 1
                self.tally.reasons[f'{kind}: {exc}'[:120]] += 1
                return None
            except Exception as exc:  # noqa: BLE001 — every other kind is a finding
                await session.rollback()
                self.tally.errors.append(f'{kind}: {type(exc).__name__}: {exc}'[:300])
                return None
        self.tally.ok[kind] += 1
        return result

    async def _draft(self, session: AsyncSession, data: DocumentCreate) -> uuid.UUID:
        doc = await create_document(session, self.wh.org_id, data, self.wh.user_id)
        await confirm_document(session, self.wh.org_id, doc.id, self.wh.user_id)
        return doc.id

    async def _a_record(
        self,
        session: AsyncSession,
        template: uuid.UUID,
        shelf: uuid.UUID,
        at_least: Decimal = Decimal(0),
    ) -> uuid.UUID:
        """A record of the product on the shelf, the way a person picks one from the list."""
        record: uuid.UUID | None = await session.scalar(
            select(Item.id)
            .where(
                Item.organization_id == self.wh.org_id,
                Item.template_id == template,
                Item.storage_location_id == shelf,
                Item.is_deleted.is_(False),
                Item.quantity > at_least,
            )
            .order_by(Item.id)
            .limit(1)
        )
        if record is None:
            raise LookupError('no record of the product on the shelf')
        return record

    def hold(
        self, lines: list[tuple[uuid.UUID, Decimal]], shelf: uuid.UUID
    ) -> _Door[uuid.UUID]:
        # An issue names a record on each line — the list a person picks
        # from — and takes by the product's removal order across the shelf.
        async def door(session: AsyncSession) -> uuid.UUID:
            data = DocumentCreate(
                type='OUT',
                source_location_id=shelf,
                lines=[
                    DocumentLineCreate(
                        item_id=await self._a_record(session, template, shelf),
                        product_template_id=template,
                        expected_quantity=qty,
                    )
                    for template, qty in lines
                ],
            )
            return await self._draft(session, data)

        return door

    def complete(self, doc_id: uuid.UUID) -> _Door[bool]:
        async def door(session: AsyncSession) -> bool:
            await complete_document(
                session,
                self.wh.org_id,
                doc_id,
                self.wh.user_id,
                DocumentComplete(complete_as_planned=True),
            )
            return True

        return door

    def cancel(self, doc_id: uuid.UUID) -> _Door[bool]:
        async def door(session: AsyncSession) -> bool:
            await cancel_document(session, self.wh.org_id, doc_id, self.wh.user_id)
            return True

        return door

    def issue(
        self, lines: list[tuple[uuid.UUID, Decimal]], shelf: uuid.UUID
    ) -> _Door[uuid.UUID]:
        hold = self.hold(lines, shelf)

        async def door(session: AsyncSession) -> uuid.UUID:
            doc_id = await hold(session)
            await complete_document(
                session,
                self.wh.org_id,
                doc_id,
                self.wh.user_id,
                DocumentComplete(complete_as_planned=True),
            )
            return doc_id

        return door

    def deliver(
        self, template: uuid.UUID, shelf: uuid.UUID, qty: Decimal, batch: str | None
    ) -> _Door[uuid.UUID]:
        data = DocumentCreate(
            type='IN',
            target_location_id=shelf,
            lines=[
                DocumentLineCreate(
                    product_template_id=template,
                    expected_quantity=qty,
                    batch_number=batch,
                    expiry_date=self.wh.batches.get(batch) if batch else None,
                )
            ],
        )

        async def door(session: AsyncSession) -> uuid.UUID:
            doc_id = await self._draft(session, data)
            await complete_document(
                session,
                self.wh.org_id,
                doc_id,
                self.wh.user_id,
                DocumentComplete(complete_as_planned=True),
            )
            return doc_id

        return door

    def carry(
        self, template: uuid.UUID, source: uuid.UUID, target: uuid.UUID, qty: Decimal
    ) -> _Door[uuid.UUID]:
        async def door(session: AsyncSession) -> uuid.UUID:
            record = await self._a_record(session, template, source, at_least=qty - 1)
            data = DocumentCreate(
                type='INT',
                source_location_id=source,
                target_location_id=target,
                lines=[DocumentLineCreate(item_id=record, expected_quantity=qty)],
            )
            doc_id = await self._draft(session, data)
            await complete_document(
                session,
                self.wh.org_id,
                doc_id,
                self.wh.user_id,
                DocumentComplete(complete_as_planned=True),
            )
            return doc_id

        return door


class _Watcher:
    """Reads the committed stock every few milliseconds from a connection of its own."""

    _GROUPS = text(
        """SELECT count(*) FILTER (WHERE quantity < 0),
                  count(*) FILTER (WHERE reserved_quantity > quantity)
           FROM stock_quants_from_records WHERE organization_id = :org"""
    )
    _RECORDS = text(
        """SELECT count(*) FROM items
           WHERE organization_id = :org AND is_deleted IS FALSE AND quantity < 0"""
    )
    _OVER_HELD = text(
        """SELECT product_template_id, storage_location_id, lot_id, owner_id,
                  quantity, reserved_quantity
           FROM stock_quants_from_records
           WHERE organization_id = :org AND reserved_quantity > quantity"""
    )

    def __init__(
        self,
        engine: AsyncEngine,
        org_id: uuid.UUID,
        before: dict[_Key, Decimal],
        moves_before: dict[uuid.UUID, _Key],
    ) -> None:
        self.engine = engine
        self.org_id = org_id
        self.before = before
        self.moves_before = moves_before
        self.worst: Counter[str] = Counter()
        #: The groups seen holding more than they had, as the watcher read them.
        self.over_held: list[str] = []
        #: What did not add up in a snapshot taken while the others worked.
        self.unbalanced: list[str] = []
        self.samples = 0
        self.stop = asyncio.Event()

    async def _balance(self, snapshot: AsyncConnection) -> None:
        """The ledger's sum, read in one snapshot: stood + moved = stands."""
        now = await _on_hand(snapshot, self.org_id)
        moves_now = await _moves(snapshot, self.org_id)
        await snapshot.rollback()
        broken = _unbalanced(self.before, now, self.moves_before, moves_now)
        if broken and len(self.unbalanced) < 5:
            self.unbalanced.extend(broken[: 5 - len(self.unbalanced)])

    async def watch(self) -> None:
        async with self.engine.connect() as conn, self.engine.connect() as raw:
            snapshot = await raw.execution_options(isolation_level='REPEATABLE READ')
            while not self.stop.is_set():
                await self._balance(snapshot)
                groups_below, over_held = (
                    await conn.execute(self._GROUPS, {'org': self.org_id})
                ).one()
                records_below = await conn.scalar(self._RECORDS, {'org': self.org_id})
                if over_held and len(self.over_held) < 5:
                    rows = await conn.execute(self._OVER_HELD, {'org': self.org_id})
                    self.over_held.extend(str(tuple(row)) for row in rows)
                await conn.rollback()
                for name, count in (
                    ('record below zero', records_below),
                    ('group below zero', groups_below),
                    ('held over on hand', over_held),
                ):
                    self.worst[name] = max(self.worst[name], count or 0)
                self.samples += 1
                await asyncio.sleep(0.005)


_ON_HAND = text(
    """SELECT template_id, storage_location_id, lot_id, sum(quantity)
       FROM items
       WHERE organization_id = :org AND is_deleted IS FALSE AND template_id IS NOT NULL
       GROUP BY 1, 2, 3"""
)
_MOVES = text(
    """SELECT id, product_template_id, from_location_id, to_location_id, lot_id, quantity
       FROM stock_moves WHERE organization_id = :org AND state = 'done'"""
)


_Key = tuple[Any, ...]


async def _on_hand(conn: AsyncConnection, org_id: uuid.UUID) -> dict[_Key, Decimal]:
    return {
        (tpl, loc, lot): qty
        for tpl, loc, lot, qty in (await conn.execute(_ON_HAND, {'org': org_id})).all()
    }


async def _moves(conn: AsyncConnection, org_id: uuid.UUID) -> dict[uuid.UUID, _Key]:
    return {
        row[0]: tuple(row[1:])
        for row in (await conn.execute(_MOVES, {'org': org_id})).all()
    }


def _unbalanced(
    before: dict[_Key, Decimal],
    after: dict[_Key, Decimal],
    moves_before: dict[uuid.UUID, _Key],
    moves_after: dict[uuid.UUID, _Key],
) -> list[str]:
    moved: defaultdict[_Key, Decimal] = defaultdict(Decimal)
    for move_id, (tpl, source, target, lot, qty) in moves_after.items():
        if move_id in moves_before:
            continue
        if source is not None:
            moved[(tpl, source, lot)] -= qty
        if target is not None:
            moved[(tpl, target, lot)] += qty
    broken = []
    for key in set(before) | set(after) | set(moved):
        stood, stands = before.get(key, Decimal(0)), after.get(key, Decimal(0))
        if stood + moved[key] != stands:
            broken.append(f'{key}: {stood} + {moved[key]} != {stands}')
    return broken


async def _drain(hands: _Hands) -> tuple[int, list[str]]:
    """Half issue five at a time, half hold five, each until the shelf says no."""
    wh = hands.wh
    home = wh.shelves[0]
    confirmed = 0
    broken_promises: list[str] = []
    start = asyncio.Event()

    async def person(n: int) -> None:
        nonlocal confirmed
        await start.wait()
        while True:
            doc_id = await hands.attempt(
                'drain hold', hands.hold([(wh.rice, _DRAIN_EACH)], home)
            )
            if doc_id is None:
                return
            confirmed += 1
            if (
                n % 2 == 0
                and await hands.attempt('drain issue', hands.complete(doc_id)) is None
            ):
                broken_promises.append(str(doc_id))

    people = [asyncio.create_task(person(n)) for n in range(_WORKERS)]
    start.set()
    await asyncio.gather(*people)
    return confirmed, broken_promises


def _chaos_ops(n: int, wh: _Warehouse) -> Iterator[tuple[str, dict[str, Any]]]:
    rng = random.Random(f'{_SEED}-{n}')
    products = (wh.yoghurt, wh.rice, wh.flour)
    for _ in range(_CHAOS_OPS):
        kind = rng.choices(
            ('issue', 'hold', 'release', 'deliver', 'carry', 'pair'),
            weights=(25, 20, 10, 10, 15, 20),
        )[0]
        shelf = rng.choice(wh.shelves)
        template = rng.choice(products)
        yield (
            kind,
            {
                'template': template,
                'shelf': shelf,
                'other': wh.shelves[1] if shelf == wh.shelves[0] else wh.shelves[0],
                'qty': Decimal(rng.randint(1, 8)),
                'use_own': rng.random() < 0.4,
                'batch': rng.choice(sorted(wh.batches))
                if template == wh.yoghurt
                else None,
                'lines': rng.sample(
                    [
                        (wh.yoghurt, Decimal(rng.randint(1, 5))),
                        (wh.flour, Decimal(rng.randint(1, 5))),
                    ],
                    2,
                ),
                'pick': rng.random(),
            },
        )


async def _chaos(hands: _Hands) -> None:
    wh = hands.wh
    start = asyncio.Event()

    async def person(n: int) -> None:
        own: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []  # (doc, template, shelf)
        await start.wait()
        for kind, o in _chaos_ops(n, wh):
            template, shelf, qty = o['template'], o['shelf'], o['qty']
            if kind == 'issue':
                mine = [d for d in own if d[1] == template and d[2] == shelf]
                if mine and o['use_own']:
                    if await hands.attempt('issue held', hands.complete(mine[0][0])):
                        own.remove(mine[0])
                else:
                    await hands.attempt('issue', hands.issue([(template, qty)], shelf))
            elif kind == 'hold':
                doc_id = await hands.attempt(
                    'hold', hands.hold([(template, qty)], shelf)
                )
                if doc_id is not None:
                    own.append((doc_id, template, shelf))
            elif kind == 'release':
                if own:
                    held = own[int(o['pick'] * len(own))]
                    if await hands.attempt('release', hands.cancel(held[0])):
                        own.remove(held)
            elif kind == 'deliver':
                await hands.attempt(
                    'deliver', hands.deliver(template, shelf, qty, o['batch'])
                )
            elif kind == 'carry':
                await hands.attempt(
                    'carry', hands.carry(template, shelf, o['other'], qty)
                )
            else:
                await hands.attempt('pair', hands.issue(o['lines'], shelf))

    people = [asyncio.create_task(person(n)) for n in range(_WORKERS)]
    start.set()
    await asyncio.gather(*people)


@dataclass
class _Outcome:
    confirmed: int
    broken_promises: list[str]
    drain: _Tally
    chaos: _Tally
    watched: Counter[str]
    over_held: list[str]
    samples: int
    unbalanced: list[str]
    unbalanced_while_running: list[str]
    seconds: float

    def damage(self) -> dict[str, object]:
        """What went wrong, by the probe's own measures; empty when the stock is whole."""
        found: dict[str, object] = {}
        if self.confirmed != _DRAIN_RECORDS:
            found['drain confirmations'] = self.confirmed
        if self.broken_promises:
            found['confirmed issues that did not complete'] = len(self.broken_promises)
        for phase, tally in (('drain', self.drain), ('chaos', self.chaos)):
            if tally.deadlocks:
                found[f'{phase} deadlocks'] = tally.deadlocks
            if tally.timeouts:
                found[f'{phase} lock timeouts'] = dict(tally.waited)
            if tally.errors:
                found[f'{phase} errors'] = tally.errors[:5]
        worst = {name: count for name, count in self.watched.items() if count}
        if worst:
            found['watcher'] = worst
        if self.over_held:
            found['groups seen holding more than they had'] = self.over_held
        if self.unbalanced:
            found['ledger does not add up'] = self.unbalanced[:5]
        if self.unbalanced_while_running:
            found['ledger did not add up while running'] = self.unbalanced_while_running
        return found


async def _run(real_async_db_session: AsyncSession) -> _Outcome:
    wh = await _warehouse(real_async_db_session)
    engine = create_async_engine(
        _async_test_url(),
        echo=False,
        pool_size=_WORKERS + 3,
        max_overflow=0,
        # A door that holds a lock while it waits on something the database
        # cannot see would wait forever; this bound turns that into a finding.
        # Fifty people on a few groups do queue, and the queue is not one:
        # on an idle machine waits past a second are routine, for the stock
        # lock and for the numbering counter alike, and with the rest of the
        # suite running beside this test some passed ten seconds. The bound
        # sits well past any queue this test makes.
        connect_args={'server_settings': {'lock_timeout': '60s'}},
    )
    started = time.perf_counter()
    try:
        drain_hands = _Hands(engine, wh)
        confirmed, broken_promises = await _drain(drain_hands)

        hands = _Hands(engine, wh)
        async with engine.connect() as conn:
            before, moves_before = (
                await _on_hand(conn, wh.org_id),
                await _moves(conn, wh.org_id),
            )
        watcher = _Watcher(engine, wh.org_id, before, moves_before)
        watching = asyncio.create_task(watcher.watch())
        try:
            await _chaos(hands)
        finally:
            watcher.stop.set()
            await watching
        async with engine.connect() as conn:
            after, moves_after = (
                await _on_hand(conn, wh.org_id),
                await _moves(conn, wh.org_id),
            )
    finally:
        await engine.dispose()
    return _Outcome(
        confirmed=confirmed,
        broken_promises=broken_promises,
        drain=drain_hands.tally,
        chaos=hands.tally,
        watched=watcher.worst,
        over_held=watcher.over_held,
        samples=watcher.samples,
        unbalanced=_unbalanced(before, after, moves_before, moves_after),
        unbalanced_while_running=watcher.unbalanced,
        seconds=time.perf_counter() - started,
    )


async def test_fifty_people_at_once_leave_the_stock_whole(
    real_async_db_session: AsyncSession,
) -> None:
    outcome = await _run(real_async_db_session)

    assert outcome.damage() == {}, outcome
    # The probe probed: every door went through at least once, and the
    # watcher read the stock while the others worked.
    assert set(outcome.chaos.ok) >= {
        'issue',
        'hold',
        'release',
        'deliver',
        'carry',
        'pair',
    }, outcome.chaos
    assert outcome.samples >= 20, outcome.samples
