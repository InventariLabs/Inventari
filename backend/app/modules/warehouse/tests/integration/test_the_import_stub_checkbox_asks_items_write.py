"""The import stub checkbox asks for the permission founding templates takes.

Importing lines into a draft is documents work, and a documents-only
account may do it. One word in the request — ``create_stubs_for_unmatched``
— founds product templates, and founding templates is ``items:write``
work. So the flag is what the permission gates: with it on, an account
short on ``items:write`` is refused by name; with it off, the same
account imports exactly as before; with the permission held, the flag
still creates stubs.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User

MAPPING = {'name': 'name', 'barcode': 'barcode'}


@pytest.fixture
def seed_template(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    # A draft must carry at least one line; this one is not the subject.
    return h.create_template(doc_org, name=f'Seed line {uuid4().hex[:6]}')


@pytest.fixture
def docstubs_user(h: ModuleTestHelper, doc_org: Organization) -> User:
    """Documents writer without items:write — the measured role shape."""
    user = h.create_user(doc_org, email='docstubs@example.com', role='user')
    h.grant_permissions(user, ['warehouse:read', 'warehouse:write'])
    return user


@pytest.fixture
def items_writer_user(h: ModuleTestHelper, doc_org: Organization) -> User:
    user = h.create_user(doc_org, email='stubs-writer@example.com', role='user')
    h.grant_permissions(
        user, ['warehouse:read', 'warehouse:write', 'items:read', 'items:write']
    )
    return user


def _headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


def _create_draft(
    client: TestClient,
    headers: dict[str, str],
    partner_id: Any,
    target_location_id: Any,
    seed_template_id: Any,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {'product_template_id': str(seed_template_id), 'expected_quantity': 1},
            ],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return cast(str, resp.json()['id'])


def _org_template_count(db_session: Session, org: Organization) -> int:
    return len(
        list(
            db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.organization_id == org.id)
            ).all()
        )
    )


@pytest.mark.integration
class TestTheImportStubCheckboxAsksItemsWrite:
    def test_import_lines_refuses_stubs_without_items_write(
        self,
        client: TestClient,
        docstubs_user: User,
        h: ModuleTestHelper,
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
        seed_template: ProductTemplate,
    ) -> None:
        doc_id = _create_draft(
            client,
            _headers(h, docstubs_user),
            doc_partner.id,
            doc_target_location.id,
            seed_template.id,
        )
        before = _org_template_count(db_session, doc_org)

        csv_bytes = f'name,barcode\nStub przez import-lines {uuid4().hex[:6]},111111111\n'.encode()
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/import-lines',
            files={'file': ('lines.csv', csv_bytes, 'text/csv')},
            data={
                'mapping_json': json.dumps(MAPPING),
                'create_stubs_for_unmatched': 'true',
            },
            headers=_headers(h, docstubs_user),
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
        assert 'items:write' in resp.text, 'the refusal names the missing permission'
        db_session.expire_all()
        assert _org_template_count(db_session, doc_org) == before, (
            'no template was founded'
        )

    def test_import_paste_refuses_stubs_without_items_write(
        self,
        client: TestClient,
        docstubs_user: User,
        h: ModuleTestHelper,
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
        seed_template: ProductTemplate,
    ) -> None:
        doc_id = _create_draft(
            client,
            _headers(h, docstubs_user),
            doc_partner.id,
            doc_target_location.id,
            seed_template.id,
        )
        before = _org_template_count(db_session, doc_org)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/import-paste',
            json={
                'text': f'name\tbarcode\nStub z ekranu {uuid4().hex[:6]}\t222222222',
                'mapping_json': MAPPING,
                'create_stubs_for_unmatched': True,
            },
            headers=_headers(h, docstubs_user),
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
        assert 'items:write' in resp.text, 'the refusal names the missing permission'
        db_session.expire_all()
        assert _org_template_count(db_session, doc_org) == before, (
            'no template was founded'
        )

    def test_import_without_stubs_stays_open_to_documents_only(
        self,
        client: TestClient,
        docstubs_user: User,
        h: ModuleTestHelper,
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
        seed_template: ProductTemplate,
    ) -> None:
        """The default path keeps working: the line imports as unmatched."""
        doc_id = _create_draft(
            client,
            _headers(h, docstubs_user),
            doc_partner.id,
            doc_target_location.id,
            seed_template.id,
        )
        before = _org_template_count(db_session, doc_org)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/import-paste',
            json={
                'text': f'name\tbarcode\nNiedopasowany {uuid4().hex[:6]}\t333333333',
                'mapping_json': MAPPING,
            },
            headers=_headers(h, docstubs_user),
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['imported'] == 1
        assert body['unmatched'] == 1
        assert body['stubs_created'] == 0
        db_session.expire_all()
        assert _org_template_count(db_session, doc_org) == before, (
            'the documents-only account founded nothing'
        )

    def test_stubs_still_work_for_a_caller_holding_items_write(
        self,
        client: TestClient,
        items_writer_user: User,
        h: ModuleTestHelper,
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_org: Organization,
        db_session: Session,
        seed_template: ProductTemplate,
    ) -> None:
        doc_id = _create_draft(
            client,
            _headers(h, items_writer_user),
            doc_partner.id,
            doc_target_location.id,
            seed_template.id,
        )
        before = _org_template_count(db_session, doc_org)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/import-paste',
            json={
                'text': f'name\tbarcode\nLegalny stub {uuid4().hex[:6]}\t444444444',
                'mapping_json': MAPPING,
                'create_stubs_for_unmatched': True,
            },
            headers=_headers(h, items_writer_user),
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['imported'] == 1
        assert body['matched'] == 1
        assert body['stubs_created'] == 1
        db_session.expire_all()
        assert _org_template_count(db_session, doc_org) == before + 1, (
            'the legal path still founds its stub'
        )
