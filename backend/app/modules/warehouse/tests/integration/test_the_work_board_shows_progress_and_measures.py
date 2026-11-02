"""The work board reads progress and three measures from what has happened.

A card for a document under way says how many of its lines are finished, a
card that is done says when, and the strip above the board counts what the
records already hold: how long a delivery took from the first scan to being
posted, how many orders left on the day they were raised, and nothing typed
in by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    WmsPickSession,
    WorkItemOverlay,
)

_TODAY = date.today()


def _document(
    db_session: Session,
    org: Organization,
    user: User,
    *,
    doc_type: str,
    status_word: str,
    done: tuple[int, int] = (0, 1),
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> Document:
    """A document of ``done[1]`` lines, ``done[0]`` of them finished."""
    finished, total = done
    document = Document(
        organization_id=org.id,
        type=doc_type,
        number=f'{doc_type}/{uuid4().hex[:8]}',
        status=status_word,
        scheduled_date=_TODAY,
        created_by=user.id,
        completed_at=completed_at,
    )
    if created_at is not None:
        document.created_at = created_at
    document.lines = [
        DocumentLine(
            name=f'Line {number}',
            quantity=Decimal('4'),
            expected_quantity=Decimal('4'),
            done_quantity=Decimal('4') if number < finished else Decimal('0'),
            line_number=number + 1,
        )
        for number in range(total)
    ]
    db_session.add(document)
    db_session.commit()
    return document


def _session(
    db_session: Session,
    org: Organization,
    user: User,
    document: Document,
    *,
    started_at: datetime,
    status_word: str = 'completed',
) -> None:
    db_session.add(
        WmsPickSession(
            organization_id=org.id,
            document_id=document.id,
            assigned_to=user.id,
            status=status_word,
            started_at=started_at,
        )
    )
    db_session.commit()


def _todo(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': _TODAY.isoformat(), 'limit': 50, **params},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json()['work_items'])


def _measures(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get('/api/v1/warehouse/work-items/measures', headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.integration
class TestACardCarriesItsProgress:
    def test_a_document_under_way_counts_its_finished_lines(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        document = _document(
            db_session, doc_org, doc_user,
            doc_type='OUT', status_word='CONFIRMED', done=(2, 3),
        )  # fmt: skip
        _session(
            db_session, doc_org, doc_user, document,
            started_at=datetime.now(UTC), status_word='active',
        )  # fmt: skip

        items = _todo(client, doc_auth_headers)['items']

        card = next(item for item in items if item['source_id'] == str(document.id))
        assert card['state'] == 'in_progress'
        assert Decimal(card['count']) == 3
        assert card['lines_done'] == 2

    def test_a_document_posted_and_a_task_ticked_say_when(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        posted_at = datetime.now(UTC) - timedelta(minutes=5)
        document = _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED', completed_at=posted_at,
        )  # fmt: skip
        ticked = WorkItemOverlay(
            organization_id=doc_org.id,
            source_kind='custom',
            title='Move the rack',
            created_by=doc_user.id,
            done_at=posted_at,
        )
        db_session.add(ticked)
        db_session.commit()

        items = _todo(client, doc_auth_headers, include_done=True)['items']

        by_source = {item['source_id']: item for item in items}
        for source_id in (str(document.id), str(ticked.id)):
            stamp = datetime.fromisoformat(by_source[source_id]['done_at'])
            assert abs(stamp - posted_at) < timedelta(seconds=1)

    def test_an_open_task_has_no_done_time(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        document = _document(
            db_session, doc_org, doc_user, doc_type='OUT', status_word='CONFIRMED'
        )

        items = _todo(client, doc_auth_headers)['items']

        card = next(item for item in items if item['source_id'] == str(document.id))
        assert card['done_at'] is None


@pytest.mark.integration
class TestTheStripMeasuresWhatHappenedThisWeek:
    def test_an_empty_week_has_nothing_to_average(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        assert _measures(client, doc_auth_headers) == {
            'dock_to_stock_seconds': None,
            'dock_to_stock_count': 0,
            'shipped_same_day': 0,
            'shipped_total': 0,
        }

    def test_dock_to_stock_is_the_first_scan_to_the_posting(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        for hours in (2, 4):
            receipt = _document(
                db_session, doc_org, doc_user,
                doc_type='IN', status_word='COMPLETED', completed_at=now,
            )  # fmt: skip
            # A second, later session must not move the start of the clock.
            _session(
                db_session, doc_org, doc_user, receipt,
                started_at=now - timedelta(hours=hours),
            )  # fmt: skip
            _session(
                db_session, doc_org, doc_user, receipt,
                started_at=now - timedelta(minutes=10),
            )  # fmt: skip
        # A receipt nobody scanned has no arrival to measure from; one
        # posted last month is not this week's.
        _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED', completed_at=now,
        )  # fmt: skip
        old = _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            completed_at=now - timedelta(days=30),
        )  # fmt: skip
        _session(
            db_session, doc_org, doc_user, old,
            started_at=now - timedelta(days=31),
        )  # fmt: skip

        measures = _measures(client, doc_auth_headers)

        assert measures['dock_to_stock_count'] == 2
        assert measures['dock_to_stock_seconds'] == 3 * 3600

    def test_an_order_counts_as_same_day_when_it_left_the_day_it_was_raised(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        _document(
            db_session, doc_org, doc_user,
            doc_type='OUT', status_word='COMPLETED',
            created_at=now, completed_at=now,
        )  # fmt: skip
        _document(
            db_session, doc_org, doc_user,
            doc_type='OUT', status_word='COMPLETED',
            created_at=now - timedelta(days=3), completed_at=now,
        )  # fmt: skip
        # Posted last week, and a receipt: neither is an order shipped.
        _document(
            db_session, doc_org, doc_user,
            doc_type='OUT', status_word='COMPLETED',
            created_at=now - timedelta(days=9),
            completed_at=now - timedelta(days=8),
        )  # fmt: skip
        _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            created_at=now, completed_at=now,
        )  # fmt: skip

        measures = _measures(client, doc_auth_headers)

        assert measures['shipped_total'] == 2
        assert measures['shipped_same_day'] == 1

    def test_another_organizations_work_is_not_counted(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        h: Any,
    ) -> None:
        other = h.create_org('Elsewhere', ['core', 'warehouse'])
        stranger = h.create_user(other, email='elsewhere@example.com')
        now = datetime.now(UTC)
        _document(
            db_session, other, stranger,
            doc_type='OUT', status_word='COMPLETED',
            created_at=now, completed_at=now,
        )  # fmt: skip

        assert _measures(client, doc_auth_headers)['shipped_total'] == 0


@pytest.mark.integration
class TestEveryColumnLooksThroughTheWholeSet:
    """A column, a person and "today" are asked of the server, not cut from a page."""

    def test_a_column_is_not_crowded_out_by_the_cards_before_it(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        for _ in range(3):
            _document(
                db_session, doc_org, doc_user, doc_type='OUT', status_word='CONFIRMED'
            )
        posted = _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            completed_at=datetime.now(UTC) - timedelta(minutes=5),
        )  # fmt: skip

        section = _todo(
            client, doc_auth_headers, state='done', include_done=True, work_limit=1
        )

        assert [item['source_id'] for item in section['items']] == [str(posted.id)]
        assert section['total'] == 1

    def test_the_total_of_a_column_counts_every_card_in_it(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        for _ in range(3):
            _document(
                db_session, doc_org, doc_user, doc_type='OUT', status_word='CONFIRMED'
            )

        section = _todo(client, doc_auth_headers, state='todo', work_limit=2)

        assert len(section['items']) == 2
        assert section['total'] == 3

    def test_a_person_is_found_wherever_their_card_lies(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        cards = [
            WorkItemOverlay(
                organization_id=doc_org.id,
                source_kind='custom',
                title=f'Card {number}',
                created_by=doc_user.id,
                due_date=_TODAY - timedelta(days=10 - number),
                assignee_id=doc_user.id if number == 9 else None,
            )
            for number in range(10)
        ]
        db_session.add_all(cards)
        db_session.commit()

        mine = _todo(client, doc_auth_headers, assignee=str(doc_user.id), work_limit=2)
        nobody = _todo(client, doc_auth_headers, assignee='none', work_limit=2)

        assert [item['source_id'] for item in mine['items']] == [str(cards[9].id)]
        assert mine['total'] == 1
        assert nobody['total'] == 9
        assert len(nobody['items']) == 2

    def test_today_starts_where_the_reader_says_not_a_day_ago(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            completed_at=now - timedelta(hours=5),
        )  # fmt: skip
        recent = _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            completed_at=now - timedelta(hours=1),
        )  # fmt: skip
        ticked = WorkItemOverlay(
            organization_id=doc_org.id,
            source_kind='custom',
            title='Yesterday evening',
            created_by=doc_user.id,
            done_at=now - timedelta(hours=5),
        )
        db_session.add(ticked)
        db_session.commit()

        section = _todo(
            client,
            doc_auth_headers,
            state='done',
            done_since=(now - timedelta(hours=2)).isoformat(),
        )

        assert [item['source_id'] for item in section['items']] == [str(recent.id)]

    def test_today_never_reaches_further_back_than_a_day(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        _document(
            db_session, doc_org, doc_user,
            doc_type='IN', status_word='COMPLETED',
            completed_at=datetime.now(UTC) - timedelta(days=3),
        )  # fmt: skip

        section = _todo(
            client,
            doc_auth_headers,
            state='done',
            done_since=(datetime.now(UTC) - timedelta(days=5)).isoformat(),
        )

        assert section['items'] == []

    def test_a_filter_reads_past_the_sources_first_thousand(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """The last of 1001 late documents is still its person's card, and counted."""
        documents = [
            Document(
                organization_id=doc_org.id,
                type='OUT',
                number=f'OUT/BULK/{number:04d}',
                status='CONFIRMED',
                scheduled_date=_TODAY - timedelta(days=2 if number < 1000 else 1),
                created_by=doc_user.id,
            )
            for number in range(1001)
        ]
        db_session.add_all(documents)
        db_session.flush()
        db_session.add(
            WorkItemOverlay(
                organization_id=doc_org.id,
                source_kind='document',
                source_id=documents[-1].id,
                created_by=doc_user.id,
                assignee_id=doc_user.id,
            )
        )
        db_session.commit()

        mine = _todo(client, doc_auth_headers, assignee=str(doc_user.id), work_limit=5)
        late = _todo(client, doc_auth_headers, view='overdue', work_limit=1)

        assert [item['source_id'] for item in mine['items']] == [str(documents[-1].id)]
        assert mine['total'] == 1
        assert late['total'] == 1001
