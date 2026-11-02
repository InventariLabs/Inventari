"""A picking session walks the warehouse in the order its locations are numbered.

Shelf codes rarely say how a warehouse is walked: "C-01" may be the first
rack past the door and "A-07" the last. Picking used to sort its lines by the
shelf code alone, so a worker crossed the hall back and forth. A location now
carries a plain ordering number, and a session's lines follow the numbers of
the locations they are picked from — each ancestor's number first, then the
location's own. A location nobody numbered comes after the numbered ones,
and when nothing is numbered the old order by code stays.

A dispatch takes from one location, so the lines of one document share it;
the order matters for a session that picks several dispatches at once. These
tests build such a session from the lines of one dispatch per shelf and ask
the ordering pass for its walk.
"""

import uuid
from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse._picking_helpers import (
    _assign_optimized_pick_order_async,
)
from app.modules.warehouse.models import WmsPickLine
from tests.integration._shelf import run_in_async_session


def _location(
    db: Session,
    org: Organization,
    user: User,
    *,
    code: str,
    sequence: int | None,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    location = StorageLocation(
        name=f'Shelf {code}',
        short_code=code,
        sequence=sequence,
        parent_id=parent.id if parent else None,
        organization_id=org.id,
        created_by=user.id,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def _start_dispatch_from(
    client: TestClient,
    db: Session,
    auth_headers: dict[str, str],
    org: Organization,
    partner: Partner,
    shelf: StorageLocation,
) -> uuid.UUID:
    """A confirmed dispatch of one product off *shelf*, with picking started."""
    item = Item(
        name=f'Product on {shelf.short_code}',
        organization_id=org.id,
        storage_location_id=shelf.id,
        quantity=Decimal('10'),
    )
    db.add(item)
    db.commit()
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=auth_headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(shelf.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': 1}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=auth_headers
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return uuid.UUID(resp.json()['id'])


def _walk(
    client: TestClient,
    db: Session,
    engine: AsyncEngine,
    auth_headers: dict[str, str],
    org: Organization,
    partner: Partner,
    shelves: list[StorageLocation],
) -> list[str]:
    """One session over a dispatch from each shelf; its products in pick order."""
    sessions = [
        _start_dispatch_from(client, db, auth_headers, org, partner, shelf)
        for shelf in shelves
    ]
    db.execute(
        update(WmsPickLine)
        .where(WmsPickLine.session_id.in_(sessions))
        .values(session_id=sessions[0])
    )
    db.commit()

    async def _order(session: AsyncSession) -> None:
        await _assign_optimized_pick_order_async(session, sessions[0])

    run_in_async_session(engine, _order)
    db.expire_all()
    lines = db.scalars(
        select(WmsPickLine)
        .where(WmsPickLine.session_id == sessions[0])
        .order_by(WmsPickLine.pick_order)
    ).all()
    return [cast(str, line.product_name) for line in lines]


@pytest.mark.integration
class TestThePickPathFollowsTheLocationSequence:
    def test_lines_follow_the_numbers_not_the_codes(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        # Alphabetically A, B, C — numbered so the walk is C, A, B.
        shelves = [
            _location(db_session, doc_org, doc_user, code='B-01', sequence=30),
            _location(db_session, doc_org, doc_user, code='C-01', sequence=10),
            _location(db_session, doc_org, doc_user, code='A-01', sequence=20),
        ]

        assert _walk(
            client,
            db_session,
            async_engine_fixture,
            doc_auth_headers,
            doc_org,
            doc_partner,
            shelves,
        ) == ['Product on C-01', 'Product on A-01', 'Product on B-01']

    def test_a_location_without_a_number_comes_last(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        shelves = [
            _location(db_session, doc_org, doc_user, code='A-00', sequence=None),
            _location(db_session, doc_org, doc_user, code='Z-02', sequence=2),
            _location(db_session, doc_org, doc_user, code='Z-01', sequence=1),
        ]

        assert _walk(
            client,
            db_session,
            async_engine_fixture,
            doc_auth_headers,
            doc_org,
            doc_partner,
            shelves,
        ) == ['Product on Z-01', 'Product on Z-02', 'Product on A-00']

    def test_an_aisle_number_comes_before_the_shelf_number(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        """The path is the ancestors' numbers, then the location's own."""
        near = _location(db_session, doc_org, doc_user, code='AISLE-N', sequence=1)
        far = _location(db_session, doc_org, doc_user, code='AISLE-F', sequence=2)
        shelves = [
            _location(
                db_session, doc_org, doc_user, code='F-1', sequence=1, parent=far
            ),
            _location(
                db_session, doc_org, doc_user, code='N-0', sequence=None, parent=near
            ),
            _location(
                db_session, doc_org, doc_user, code='N-9', sequence=9, parent=near
            ),
        ]

        assert _walk(
            client,
            db_session,
            async_engine_fixture,
            doc_auth_headers,
            doc_org,
            doc_partner,
            shelves,
        ) == ['Product on N-9', 'Product on N-0', 'Product on F-1']

    def test_without_any_number_the_order_is_by_code(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        """Nesting alone does not move a shelf: the code decides, as it did."""
        hall = _location(db_session, doc_org, doc_user, code='HALL', sequence=None)
        shelves = [
            _location(db_session, doc_org, doc_user, code='C-01', sequence=None),
            _location(
                db_session, doc_org, doc_user, code='A-05', sequence=None, parent=hall
            ),
            _location(db_session, doc_org, doc_user, code='B-01', sequence=None),
        ]

        assert _walk(
            client,
            db_session,
            async_engine_fixture,
            doc_auth_headers,
            doc_org,
            doc_partner,
            shelves,
        ) == ['Product on A-05', 'Product on B-01', 'Product on C-01']
