"""Closing a month, and reopening it, are events worth keeping.

Closing an accounting period is the highest-weight act a bookkeeper
performs, and neither closing nor reopening reached the organization log at
all. Worse, reopening set ``closed_at`` and ``closed_by`` back to NULL — so
the only trace that the month had ever been closed, and by whom, was erased
by the act of undoing it. What was left could not distinguish "this month
was never closed" from "somebody closed it in March and reopened it in
June".

Both stamps stay now, and which of the two happened last is what "closed"
means. The log carries the sequence.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization


def _period_entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'inventory_period',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestClosingAMonthIsAnEvent:
    def test_closing_and_reopening_both_reach_the_log(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        close = client.post(
            '/api/v1/warehouse/periods/2026/3/close',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 3, 'notes': 'March closed'},
        )
        assert close.status_code == status.HTTP_200_OK, close.text

        reopen = client.post(
            '/api/v1/warehouse/periods/2026/3/reopen',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 3, 'notes': 'invoice arrived late'},
        )
        assert reopen.status_code == status.HTTP_200_OK, reopen.text

        db_session.expire_all()
        entries = _period_entries(db_session, doc_org.id)
        assert len(entries) == 2
        first, second = entries[0].snapshot, entries[1].snapshot
        assert first is not None and second is not None
        assert first['after']['closed'] is True
        assert second['after']['closed'] is False
        assert entries[1].reason == 'invoice arrived late'

    def test_reopening_does_not_erase_who_closed_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        client.post(
            '/api/v1/warehouse/periods/2026/4/close',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 4},
        )
        reopen = client.post(
            '/api/v1/warehouse/periods/2026/4/reopen',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 4},
        )
        assert reopen.status_code == status.HTTP_200_OK, reopen.text
        body = reopen.json()

        assert body['is_closed'] is False
        # The proof of the closure survives the undo.
        assert body['closed_at'] is not None
        assert body['closed_by'] is not None
        assert body['reopened_at'] is not None

    def test_a_reopened_month_accepts_work_again(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Keeping ``closed_at`` must not leave the month locked."""
        client.post(
            '/api/v1/warehouse/periods/2026/5/close',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 5},
        )
        client.post(
            '/api/v1/warehouse/periods/2026/5/reopen',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 5},
        )
        listed = client.get(
            '/api/v1/warehouse/periods?year=2026', headers=doc_auth_headers
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        may = next(p for p in listed.json()['items'] if p['month'] == 5)
        assert may['is_closed'] is False

        # And closing it a second time is allowed, since it is open.
        again = client.post(
            '/api/v1/warehouse/periods/2026/5/close',
            headers=doc_auth_headers,
            json={'year': 2026, 'month': 5},
        )
        assert again.status_code == status.HTTP_200_OK, again.text
        assert again.json()['is_closed'] is True
