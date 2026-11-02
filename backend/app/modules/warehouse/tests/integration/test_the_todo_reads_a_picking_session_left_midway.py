"""To do reads a picking session the picker walked away from as work under way.

Closing the picking sheet mid-way pauses the session instead of leaving it
running, and To do used to count only a running session as work in
progress; anything else was judged by the lines' picked quantities. A picker
who picked a line, took it back and closed the sheet left a row that read as
untouched and offered *Pick*; one who picked one line of two and closed it
left a row offering *Complete* — the action for a dispatch picked in full —
with nobody named as holding it.

A session left paused is the same work as one still being scanned: the row
is in progress, names who left it and offers *Resume*, however much was
picked. *Complete* waits for the session to end with every line picked or
answered short.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import WmsPickLine, WmsPickSession
from app.modules.warehouse.tests.integration._records import sow

_TODAY = date.today().isoformat()

pytestmark = pytest.mark.integration


class _Picking:
    """One confirmed dispatch of two lines, and the session picking it."""

    def __init__(
        self,
        client: TestClient,
        headers: dict[str, str],
        db_session: Session,
        template: ProductTemplate,
        doc_id: str,
    ) -> None:
        self.client = client
        self.headers = headers
        self.db_session = db_session
        self.template = template
        self.doc_id = doc_id
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start', headers=headers
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text
        self.session_id = cast(str, started.json()['id'])

    def _url(self, step: str) -> str:
        return f'/api/v1/warehouse/documents/{self.doc_id}/picking/{self.session_id}/{step}'

    def _line(self, line_status: str) -> WmsPickLine:
        self.db_session.expire_all()
        line = self.db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == self.session_id,
                WmsPickLine.status == line_status,
            )
        ).first()
        assert line is not None, f'no {line_status} line in the session'
        return line

    def scan(self, quantity: int) -> None:
        scanned = self.client.post(
            self._url('scan'),
            headers=self.headers,
            json={'barcode': self.template.barcode, 'quantity': quantity},
        )
        assert scanned.status_code == status.HTTP_200_OK, scanned.text

    def undo(self) -> None:
        undone = self.client.post(
            self._url('undo'),
            headers=self.headers,
            params={'line_id': str(self._line('picked').id)},
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text

    def skip(self) -> None:
        skipped = self.client.post(
            self._url('skip'),
            headers=self.headers,
            params={'line_id': str(self._line('pending').id)},
        )
        assert skipped.status_code == status.HTTP_200_OK, skipped.text

    def close_the_sheet(self) -> None:
        paused = self.client.post(self._url('pause'), headers=self.headers)
        assert paused.status_code == status.HTTP_204_NO_CONTENT, paused.text

    def session_status(self) -> str:
        self.db_session.expire_all()
        session = self.db_session.get(WmsPickSession, UUID(self.session_id))
        assert session is not None
        return session.status


@pytest.fixture
def picking(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_partner: Partner,
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_item: Item,
) -> _Picking:
    """A dispatch of 5 and 3 with the stock to pick it, its session started.

    Two lines, so one picked line leaves the session running: picking the
    last one ends it.
    """
    sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '20',
    )
    template_id = doc_item.template_id or doc_template.id
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=doc_auth_headers,
        json={
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'scheduled_date': _TODAY,
            'lines': [
                {
                    'item_id': str(doc_item.id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
                for quantity in (5, 3)
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return _Picking(client, doc_auth_headers, db_session, doc_template, doc_id)


def _task(picking: _Picking) -> dict[str, Any]:
    """The dispatch's row on To do, as the page reads it."""
    response = picking.client.get(
        '/api/v1/warehouse/todo',
        headers=picking.headers,
        params={'date_to': _TODAY},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    for item in response.json()['work_items']['items']:
        if item['key'] == f'document:{picking.doc_id}:ship':
            return cast(dict[str, Any], item)
    raise AssertionError(f'{picking.doc_id} is not on To do: {response.json()}')


def _holder(user: User) -> str:
    return user.full_name or user.email


class TestToDoReadsAPickingSessionLeftMidway:
    def test_a_session_still_being_scanned_is_resumed_from_its_holder(
        self, picking: _Picking, doc_user: User
    ) -> None:
        picking.scan(5)

        task = _task(picking)

        assert task['state'] == 'in_progress'
        assert task['next_action'] == 'resume'
        assert task['stage_holder_name'] == _holder(doc_user)

    def test_a_sheet_closed_with_nothing_picked_is_still_work_under_way(
        self, picking: _Picking, doc_user: User
    ) -> None:
        """Pick a line, take it back, close: the session is open, not unstarted."""
        picking.scan(5)
        picking.undo()
        picking.close_the_sheet()
        assert picking.session_status() == 'paused'

        task = _task(picking)

        assert task['state'] == 'in_progress'
        assert task['next_action'] == 'resume'
        assert task['stage_holder_name'] == _holder(doc_user)

    def test_a_sheet_closed_half_picked_offers_resume_not_complete(
        self, picking: _Picking, doc_user: User
    ) -> None:
        """One line of two picked is not a picked dispatch."""
        picking.scan(5)
        picking.close_the_sheet()
        assert picking.session_status() == 'paused'

        task = _task(picking)

        assert task['state'] == 'in_progress'
        assert task['next_action'] == 'resume'
        assert task['stage_holder_name'] == _holder(doc_user)

    def test_a_session_ended_with_every_line_picked_offers_complete(
        self, picking: _Picking
    ) -> None:
        picking.scan(5)
        picking.scan(3)
        assert picking.session_status() == 'completed'

        task = _task(picking)

        assert task['state'] == 'in_progress'
        assert task['next_action'] == 'complete'
        assert task['stage_holder_name'] is None

    def test_a_session_ended_with_a_line_skipped_offers_complete(
        self, picking: _Picking
    ) -> None:
        """A skipped line is answered: nothing on it is left to pick."""
        picking.scan(5)
        picking.skip()
        assert picking.session_status() == 'completed'

        task = _task(picking)

        assert task['state'] == 'in_progress'
        assert task['next_action'] == 'complete'
        assert task['stage_holder_name'] is None
