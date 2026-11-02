"""The picking order is a strategy the organization chooses, not a fork.

The walk used to be one hard-coded pass over the lines: the numbers on the
locations, then the code, then the name. A warehouse that picks by another
rule — a zone first, a route a module computes — had no way in short of a
fork of the picking code. A module now registers a named strategy through
``warehouse_api``, the organization names one in the warehouse settings, and
the session's lines are ordered by the strategy that choice resolves to.

These tests walk one zone dispatch — a line per shelf, in the order the
warehouse is walked — under two registered strategies, under nothing chosen
(the default, registered the same way), and with the owning module switched
off (which falls back to the default without an error).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse._picking_helpers import (
    _assign_optimized_pick_order_async,
)
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import WmsPickLine
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)
from app.modules.warehouse.warehouse_api import warehouse_api
from tests.integration._shelf import run_in_async_session

_MODULE = 'walk_planner'
_BY_CODE = 'by_code'
_BY_CODE_DESC = 'by_code_desc'


def _code(line: Any) -> str:
    return (line.location_path[-1].short_code if line.location_path else '') or ''


async def _by_code(db: Any, org_id: UUID, lines: list[Any]) -> list[Any]:
    """Shelf codes, ascending — the order a worker reads the labels in."""
    return sorted(lines, key=_code)


async def _by_code_desc(db: Any, org_id: UUID, lines: list[Any]) -> list[Any]:
    return sorted(lines, key=_code, reverse=True)


class _WalkPlanner:
    """The module under test: its two strategies and what they were asked."""

    def __init__(self) -> None:
        self.seen: list[list[Any]] = []

    async def record_and_by_code(
        self, db: Any, org_id: UUID, lines: list[Any]
    ) -> list[Any]:
        self.seen.append(list(lines))
        return await _by_code(db, org_id, lines)

    def register(self) -> None:
        warehouse_api.register_pick_order_strategy(
            _MODULE, _BY_CODE, self.record_and_by_code
        )
        warehouse_api.register_pick_order_strategy(
            _MODULE, _BY_CODE_DESC, _by_code_desc
        )


@pytest.fixture
def walk_planner(db_session: Session, doc_org: Organization) -> _WalkPlanner:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    planner = _WalkPlanner()
    planner.register()
    return planner


def _choose(
    db_session: Session,
    engine: AsyncEngine,
    org: Organization,
    name: str | None,
) -> None:
    """Name *name* in the warehouse settings — the organization's own choice."""

    async def _set(session: AsyncSession) -> None:
        profile = await get_or_create_profile(session, org.id)
        profile.pick_order_strategy = name

    db_session.commit()
    run_in_async_session(engine, _set)
    db_session.expire_all()


def _shelf(
    db_session: Session,
    org: Organization,
    user: User,
    parent: StorageLocation,
    *,
    name: str,
    code: str,
    sequence: int,
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org.id,
        name=name,
        short_code=code,
        sequence=sequence,
        parent_id=parent.id,
        storage_type_id=parent.storage_type_id,
        created_by=user.id,
    )
    db_session.add(shelf)
    db_session.flush()
    return shelf


def _walk_zone(
    client: TestClient,
    db_session: Session,
    engine: AsyncEngine,
    org: Organization,
    headers: dict[str, str],
    partner: Partner,
    template: ProductTemplate,
    source: StorageLocation,
    shelves: list[StorageLocation],
) -> UUID:
    """One confirmed zone dispatch and the id of its picking session.

    Two records per shelf, and the line takes exactly that much: the draw
    reaches every shelf, so the session gets one line per shelf.
    """
    first = [
        _sow(
            db_session,
            engine,
            org,
            template,
            shelf.id,
            Decimal('2'),
        )
        for shelf in shelves
    ][0]

    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'lines': [
                {
                    'item_id': str(first.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': 2 * len(shelves),
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    started = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=headers
    )
    assert started.status_code == status.HTTP_201_CREATED, started.text
    return UUID(cast(str, started.json()['id']))


def _codes_in_order(
    db_session: Session,
    session_id: UUID,
    by_id: dict[UUID, StorageLocation],
) -> list[str]:
    db_session.expire_all()
    lines = db_session.scalars(
        select(WmsPickLine)
        .where(WmsPickLine.session_id == session_id)
        .order_by(WmsPickLine.pick_order)
    ).all()
    return [
        by_id[cast(UUID, line.location_id)].short_code or ''
        for line in lines
        if line.location_id is not None
    ]


def _three_shelves(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_source_location: StorageLocation,
) -> list[StorageLocation]:
    """A-01, B-02, C-03 — numbered so the default walk takes them B, C, A."""
    return [
        _shelf(
            db_session,
            doc_org,
            doc_user,
            doc_source_location,
            name='Shelf A',
            code='A-01',
            sequence=3,
        ),
        _shelf(
            db_session,
            doc_org,
            doc_user,
            doc_source_location,
            name='Shelf B',
            code='B-02',
            sequence=1,
        ),
        _shelf(
            db_session,
            doc_org,
            doc_user,
            doc_source_location,
            name='Shelf C',
            code='C-03',
            sequence=2,
        ),
    ]


@pytest.mark.integration
class TestAModuleCanWalkTheWarehouseItsOwnWay:
    def test_the_organization_walks_the_warehouse_the_way_it_chose(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        walk_planner: _WalkPlanner,
    ) -> None:
        shelves = _three_shelves(db_session, doc_org, doc_user, doc_source_location)
        by_id = {shelf.id: shelf for shelf in shelves}

        _choose(db_session, async_engine_fixture, doc_org, _BY_CODE)
        session_id = _walk_zone(
            client,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_auth_headers,
            doc_partner,
            doc_template,
            doc_source_location,
            shelves,
        )
        assert _codes_in_order(db_session, session_id, by_id) == [
            'A-01',
            'B-02',
            'C-03',
        ]

        # The same session, re-walked under the other registered strategy:
        # the choice names the strategy, and the pass asks the registry again.
        _choose(db_session, async_engine_fixture, doc_org, _BY_CODE_DESC)

        async def _rewalk(session: AsyncSession) -> None:
            await _assign_optimized_pick_order_async(session, session_id)

        run_in_async_session(async_engine_fixture, _rewalk)
        assert _codes_in_order(db_session, session_id, by_id) == [
            'C-03',
            'B-02',
            'A-01',
        ]

    def test_the_default_order_stands_when_nothing_is_chosen(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        walk_planner: _WalkPlanner,
    ) -> None:
        """The default is registered like any other — and is what nothing means."""
        shelves = _three_shelves(db_session, doc_org, doc_user, doc_source_location)
        by_id = {shelf.id: shelf for shelf in shelves}

        _choose(db_session, async_engine_fixture, doc_org, None)
        session_id = _walk_zone(
            client,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_auth_headers,
            doc_partner,
            doc_template,
            doc_source_location,
            shelves,
        )
        assert _codes_in_order(db_session, session_id, by_id) == [
            'B-02',
            'C-03',
            'A-01',
        ]

    def test_a_disabled_modules_strategy_falls_back_to_the_default(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
    ) -> None:
        """A choice the module behind it cannot answer is the default, not a refusal.

        The strategy stays registered — registration is at import time and
        knows no organization — but the module is switched off here, so the
        walk takes the default order and the session starts as always.
        """
        _WalkPlanner().register()
        shelves = _three_shelves(db_session, doc_org, doc_user, doc_source_location)
        by_id = {shelf.id: shelf for shelf in shelves}

        _choose(db_session, async_engine_fixture, doc_org, _BY_CODE)
        session_id = _walk_zone(
            client,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_auth_headers,
            doc_partner,
            doc_template,
            doc_source_location,
            shelves,
        )
        assert _codes_in_order(db_session, session_id, by_id) == [
            'B-02',
            'C-03',
            'A-01',
        ]

    def test_a_strategy_is_asked_with_the_product_quantity_and_path(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        walk_planner: _WalkPlanner,
    ) -> None:
        shelves = [
            _shelf(
                db_session,
                doc_org,
                doc_user,
                doc_source_location,
                name='Shelf A',
                code='A-01',
                sequence=1,
            ),
            _shelf(
                db_session,
                doc_org,
                doc_user,
                doc_source_location,
                name='Shelf B',
                code='B-02',
                sequence=2,
            ),
        ]
        _choose(db_session, async_engine_fixture, doc_org, _BY_CODE)
        _walk_zone(
            client,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_auth_headers,
            doc_partner,
            doc_template,
            doc_source_location,
            shelves,
        )

        assert walk_planner.seen, 'the chosen strategy was never asked'
        lines = walk_planner.seen[-1]
        assert len(lines) == len(shelves)
        for line in lines:
            assert line.product_name
            assert line.quantity > 0
            assert line.location_id is not None
            # The path is the walk-in: the zone first, then the shelf.
            assert [step.short_code for step in line.location_path] == [
                doc_source_location.short_code,
                next(
                    shelf.short_code
                    for shelf in shelves
                    if shelf.id == line.location_id
                ),
            ]
