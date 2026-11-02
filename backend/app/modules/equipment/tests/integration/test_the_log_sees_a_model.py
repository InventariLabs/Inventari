"""A model is a definition the whole fleet is written against.

Change the warranty period on one and sixty units inherit it, so the
catalogue half of the log is exactly where it belongs -- and none of it was
recorded: creating, editing, cloning and deleting an equipment model all
went through the core's product-template writes, which kept no journal.

The entries say `product_template`, not `equipment_model`, and that is the
point. A model *is* a product template: the same row in the same table,
reached from a second screen. Logged under its own word it would have read
as a different kind of thing depending on who opened it, and the filter
would have offered both for one act.

There is no serial number in these entries on purpose. A model is the thing
serials are told apart within.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.organization import Organization

MODELS_URL = '/api/v1/equipment/models'


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'product_template',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


def _create_model(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        MODELS_URL,
        headers=headers,
        json={
            'name': 'PowerEdge R650',
            'brand': 'Dell',
            'equipment_meta': {'warranty_months': 36},
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


@pytest.mark.integration
class TestTheLogSeesAModel:
    def test_creating_a_model_names_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Session,
    ) -> None:
        _create_model(client, eq_auth_headers)

        db_session.expire_all()
        (entry,) = _entries(db_session, eq_org.id)
        assert entry.action == 'CREATE'
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'PowerEdge R650'
        assert entry.snapshot['brand'] == 'Dell'
        assert entry.snapshot['meta_data'] == {'equipment': {'warranty_months': 36}}

    def test_an_edit_says_what_moved(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Session,
    ) -> None:
        model_id = _create_model(client, eq_auth_headers)

        response = client.put(
            f'{MODELS_URL}/{model_id}',
            headers=eq_auth_headers,
            json={'equipment_meta': {'warranty_months': 12}},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        _created, edited = _entries(db_session, eq_org.id)
        assert edited.action == 'UPDATE'
        assert edited.snapshot is not None
        assert edited.snapshot['before'] == {
            'meta_data': {'equipment': {'warranty_months': 36}}
        }
        assert edited.snapshot['after'] == {
            'meta_data': {'equipment': {'warranty_months': 12}}
        }

    def test_a_copy_of_a_model_is_a_new_definition(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Session,
    ) -> None:
        model_id = _create_model(client, eq_auth_headers)

        response = client.post(
            f'{MODELS_URL}/{model_id}/clone', headers=eq_auth_headers
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        _created, cloned = _entries(db_session, eq_org.id)
        assert cloned.action == 'CREATE'
        assert cloned.snapshot is not None
        assert cloned.snapshot['name'] == 'PowerEdge R650 (copy)'
        assert cloned.snapshot['meta_data'] == {'equipment': {'warranty_months': 36}}

    def test_deleting_the_model_keeps_the_definition(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Session,
    ) -> None:
        model_id = _create_model(client, eq_auth_headers)

        response = client.delete(f'{MODELS_URL}/{model_id}', headers=eq_auth_headers)
        assert response.status_code == 204, response.text

        db_session.expire_all()
        _created, removed = _entries(db_session, eq_org.id)
        assert removed.action == 'HARD_DELETE'
        assert removed.snapshot is not None
        assert removed.snapshot['name'] == 'PowerEdge R650'
        assert removed.snapshot['meta_data'] == {'equipment': {'warranty_months': 36}}
