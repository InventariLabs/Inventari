"""A document type's configuration leaves a readable entry in the log.

The per-type defaults decide how the next document is numbered and whether
it needs a partner, so "who changed that" must have an answer. An entry
names the type in its subject and carries only the settings that moved;
dropping the configuration reads as the settings that went away, not as a
dump of every column the row happened to hold (id, organization, stamps).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.modules.warehouse.models import DocumentTypeConfig

pytestmark = pytest.mark.integration

_URL = '/api/v1/warehouse/settings/type-configs/IN'
_SUBJECT = 'type-config:IN'


def _entries(db_session: Session, org_id: UUID) -> list[dict[str, Any]]:
    """The type-config entries of the organization, oldest first."""
    db_session.expire_all()
    rows = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'module',
        )
        .order_by(AuditLog.created_at.asc())
    ).all()
    return [
        row.snapshot or {}
        for row in rows
        if (row.snapshot or {}).get('subject') == _SUBJECT
    ]


def _rows(db_session: Session, org_id: UUID) -> int:
    db_session.expire_all()
    return (
        db_session.scalar(
            select(func.count())
            .select_from(DocumentTypeConfig)
            .where(
                DocumentTypeConfig.organization_id == org_id,
                DocumentTypeConfig.document_type == 'IN',
            )
        )
        or 0
    )


class TestTypeConfigReachesTheLog:
    def test_changing_one_setting_writes_an_entry_naming_only_that_setting(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        first = client.put(
            _URL,
            headers=doc_auth_headers,
            json={'document_type': 'IN', 'require_partner': False},
        )
        assert first.status_code == status.HTTP_200_OK, first.text
        before = len(_entries(db_session, doc_org.id))

        changed = client.put(
            _URL,
            headers=doc_auth_headers,
            json={'document_type': 'IN', 'require_partner': True},
        )
        assert changed.status_code == status.HTTP_200_OK, changed.text

        entry = _entries(db_session, doc_org.id)[before:]
        assert len(entry) == 1
        assert entry[0]['name'] == 'warehouse'
        assert entry[0]['before'] == {'require_partner': False}
        assert entry[0]['after'] == {'require_partner': True}

    def test_a_resave_that_moves_nothing_writes_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        body = {'document_type': 'IN', 'require_partner': True}
        assert (
            client.put(_URL, headers=doc_auth_headers, json=body).status_code
            == status.HTTP_200_OK
        )
        before = len(_entries(db_session, doc_org.id))

        assert (
            client.put(_URL, headers=doc_auth_headers, json=body).status_code
            == status.HTTP_200_OK
        )

        assert len(_entries(db_session, doc_org.id)) == before

    def test_dropping_the_configuration_names_settings_not_columns(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        saved = client.put(
            _URL,
            headers=doc_auth_headers,
            json={
                'document_type': 'IN',
                'sequence_format': 'PZ/{YEAR}/{SEQ:04d}',
                'require_partner': True,
            },
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text
        before = len(_entries(db_session, doc_org.id))
        assert _rows(db_session, doc_org.id) == 1

        dropped = client.delete(_URL, headers=doc_auth_headers)
        assert dropped.status_code == status.HTTP_204_NO_CONTENT, dropped.text

        assert _rows(db_session, doc_org.id) == 0
        entry = _entries(db_session, doc_org.id)[before:]
        assert len(entry) == 1
        assert entry[0]['before']['sequence_format'] == 'PZ/{YEAR}/{SEQ:04d}'
        assert entry[0]['before']['require_partner'] is True
        for column in ('id', 'organization_id', 'document_type', 'created_at'):
            assert column not in entry[0]['before'], column
            assert column not in entry[0]['after'], column
