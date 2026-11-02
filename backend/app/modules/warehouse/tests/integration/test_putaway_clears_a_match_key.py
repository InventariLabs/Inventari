"""A putaway rule can give up the match key it once had.

The update endpoint serialized the payload with ``exclude_none``, which
throws away exactly the keys the client sent as null — and the update
schema declares all four match keys clearable, the editor dialog sends
null on an emptied one. A rule matched by product template could never be
moved to category matching: the template key silently survived the save.
``exclude_unset`` keeps the payload's named keys and drops the unnamed
ones, which is the contract the screen speaks.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User


@pytest.mark.integration
class TestPutawayClearsAMatchKey:
    def test_a_rule_switched_from_template_to_category_loses_the_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PW Clear {uuid4().hex[:6]}')

        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']
        assert created.json()['product_template_id'] == str(template.id)

        category = Category(
            organization_id=doc_org.id,
            name=f'PW Clear Cat {uuid4().hex[:6]}',
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        switched = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={
                'product_template_id': None,
                'category_id': str(category.id),
            },
        )
        assert switched.status_code == 200, switched.text
        body = cast(dict[str, object], switched.json())
        assert body['product_template_id'] is None
        assert body['category_id'] == str(category.id)


@pytest.mark.integration
class TestPutawayRefusesClearingARequiredColumn:
    """Clearable (the four match keys) and optional (the whole schema) are
    different sets. The three fields backing NOT NULL columns accept an
    update and refuse a null — with the contract answer, 400, not the
    driver's null violation wearing a 500."""

    def test_a_null_priority_is_refused_with_the_contract_answer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PW Prio {uuid4().hex[:6]}')

        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']

        refused = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={'priority': None},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'priority' in refused.json()['detail']['message']

        # A non-null update to the same field still goes through.
        updated = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={'priority': 3},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()['priority'] == 3

    def test_a_null_is_active_is_refused_with_the_contract_answer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PW Act {uuid4().hex[:6]}')

        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']

        refused = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={'is_active': None},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'is_active' in refused.json()['detail']['message']

    def test_a_null_target_location_is_refused_not_looked_up(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PW Tgt {uuid4().hex[:6]}')

        created = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']

        refused = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule_id}',
            headers=doc_auth_headers,
            json={'target_location_id': None},
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'target_location_id' in refused.json()['detail']['message']
