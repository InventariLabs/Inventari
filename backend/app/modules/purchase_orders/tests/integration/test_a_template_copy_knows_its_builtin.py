"""A purchase order template copy is told about its built-in, and can go back.

A copy belongs to the organization, so nothing rewrites it. The screen can
still say that the copy differs from the layout it was made from, copy the
current layout next to it, or put the copy back as that layout, as the
warehouse and equipment screens do. The built-in is named in the seeding
language, so a copy made in one language must still match when read in another.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.template_models import DocumentTemplate

TEMPLATES = '/api/v1/purchase-orders/templates'


def _seed(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.post(f'{TEMPLATES}/seed-defaults', headers=headers)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    seeded: list[dict[str, Any]] = response.json()
    return seeded


def _row(db: Session, template_id: str) -> DocumentTemplate:
    return db.scalars(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    ).one()


def _write_into(db: Session, template_id: str) -> None:
    _row(db, template_id).body_html = '<p>our own wording</p>'
    db.commit()


@pytest.mark.integration
class TestTheCopyIsToldItDiffersFromItsBuiltIn:
    def test_a_fresh_copy_is_unmarked(
        self, client: TestClient, po_auth_headers: dict[str, str]
    ) -> None:
        _seed(client, po_auth_headers)

        listed = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
        assert listed
        assert all(not t['source_modified'] for t in listed)
        assert all(not t['source_outdated'] for t in listed)

    def test_an_edited_copy_is_marked_changed(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, po_auth_headers)
        _write_into(db_session, seeded[0]['id'])

        listed = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
        assert {t['id']: t['source_modified'] for t in listed}[seeded[0]['id']] is True

    def test_a_copy_of_an_older_layout_is_marked_outdated(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, po_auth_headers)
        _row(db_session, seeded[0]['id']).source_checksum = 'an older layout'
        db_session.commit()

        listed = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
        assert {t['id']: t['source_outdated'] for t in listed}[seeded[0]['id']] is True


@pytest.mark.integration
class TestTheCopyCanBeResetToItsBuiltIn:
    def test_a_changed_copy_becomes_the_built_in_again(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, po_auth_headers)
        original = seeded[0]['body_html']
        _write_into(db_session, seeded[0]['id'])

        response = client.post(
            f'{TEMPLATES}/{seeded[0]["id"]}/reset', headers=po_auth_headers
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['id'] == seeded[0]['id']
        assert response.json()['body_html'] == original
        listed = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
        assert all(not t['source_modified'] for t in listed)

    def test_the_language_it_was_seeded_in_does_not_hide_the_built_in(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        polish = dict(po_auth_headers, **{'Accept-Language': 'pl'})
        seeded = _seed(client, polish)
        _write_into(db_session, seeded[0]['id'])

        response = client.post(
            f'{TEMPLATES}/{seeded[0]["id"]}/reset',
            headers=dict(po_auth_headers, **{'Accept-Language': 'en'}),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['body_html'] == seeded[0]['body_html']

    def test_a_template_not_made_from_a_built_in_is_not_found(
        self, client: TestClient, po_auth_headers: dict[str, str]
    ) -> None:
        own = client.post(
            TEMPLATES,
            headers=po_auth_headers,
            json={
                'name': 'Our own',
                'document_type': 'STANDARD',
                'module': 'purchase_orders',
                'body_html': '<html><body>x</body></html>',
            },
        )
        assert own.status_code == status.HTTP_201_CREATED, own.text

        response = client.post(
            f'{TEMPLATES}/{own.json()["id"]}/reset', headers=po_auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestTheCurrentBuiltInCanBeCopiedAlongside:
    def test_the_copy_lands_beside_the_organizations_own(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, po_auth_headers)
        _write_into(db_session, seeded[0]['id'])

        response = client.post(
            f'{TEMPLATES}/{seeded[0]["id"]}/refresh-copy', headers=po_auth_headers
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        created = response.json()
        assert created['id'] != seeded[0]['id']
        assert created['is_default'] is False
        still_there = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
        assert seeded[0]['id'] in {t['id'] for t in still_there}
