"""A draft is numbered where it stands — the period it is confirmed in.

A draft carries a temporary identifier, so re-dating one changes nothing
a reader can see: there is no number yet to re-file. What has to hold is
the other half — the number drawn at confirmation carries the date the
document stands on then. A delivery drafted for December, re-dated to
January and confirmed reads a January number, and the register and the
period guard file it under January with that number.

A document that already carries a number keeps the older rule: it was
numbered in a period, and moving it to another one re-files its number
there — the disagreement (one document, two periods) the date-based
prefix exists to remove.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document


def _draft_dated(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    scheduled_date: str,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'scheduled_date': scheduled_date,
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': '2'}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _redate(
    client: TestClient, headers: dict[str, str], doc_id: str, scheduled_date: str
) -> dict[str, Any]:
    resp = client.put(
        f'/api/v1/warehouse/documents/{doc_id}',
        headers=headers,
        json={'scheduled_date': scheduled_date},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _confirm(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestADraftMovedToAnotherPeriodIsNumberedThere:
    def test_moving_a_draft_leaves_its_identifier_alone(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The draft has no period number yet, so there is nothing to move."""
        draft = _draft_dated(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2025-12-15',
        )
        assert draft['number'].startswith('DRAFT-')

        moved = _redate(client, doc_auth_headers, draft['id'], '2026-01-10')

        assert moved['scheduled_date'] == '2026-01-10'
        assert moved['number'] == draft['number']

    def test_the_number_drawn_at_confirmation_carries_the_documents_own_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The re-dated draft is numbered in the period it now stands in."""
        draft = _draft_dated(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2025-12-15',
        )
        _redate(client, doc_auth_headers, draft['id'], '2026-01-10')

        confirmed = _confirm(client, doc_auth_headers, draft['id'])

        assert confirmed['number'].startswith('IN/2026/'), confirmed['number']
        assert not confirmed['number'].startswith('IN/2025/')

    def test_a_document_already_numbered_is_renumbered_when_it_moves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The control: a number already given out still follows its date.

        A document rejected back to a draft — or written before numbering
        moved to confirmation — carries a number of its own, and leaving it
        where it was filed the register under one period and the number
        under another.
        """
        draft = _draft_dated(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2025-12-15',
        )
        row = db_session.get(Document, UUID(draft['id']))
        assert row is not None
        row.number = 'IN/2025/007'
        db_session.commit()

        moved = _redate(client, doc_auth_headers, draft['id'], '2026-01-10')

        assert moved['number'].startswith('IN/2026/'), moved['number']
        assert moved['number'] != 'IN/2025/007'

    def test_a_draft_whose_issued_number_begins_with_draft_follows_its_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The same collision at the other caller of the predicate.

        ``DRAFT-{TYPE}/{YEAR}/{SEQ:03d}`` is a legal profile format, so
        ``DRAFT-IN/2025/0003`` can be an issued number. Re-dating read it
        as a temporary identifier — nothing to re-file — and left the
        number under December while the register and the period guard
        filed the document under January: the very disagreement the
        date-based prefix exists to remove.
        """
        client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'numbering_format': 'DRAFT-{TYPE}/{YEAR}/{SEQ:03d}'},
        )
        draft = _draft_dated(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2025-12-15',
        )
        row = db_session.get(Document, UUID(draft['id']))
        assert row is not None
        row.number = 'DRAFT-IN/2025/0003'
        db_session.commit()

        moved = _redate(client, doc_auth_headers, draft['id'], '2026-01-10')

        assert moved['number'].startswith('DRAFT-IN/2026/'), moved['number']
        assert moved['number'] != 'DRAFT-IN/2025/0003'

    def test_a_draft_whose_issued_number_takes_the_whole_shape_follows_its_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The same collision at the other caller of the predicate.

        ``DRAFT-{YEAR}{SEQ:08d}`` issues ``DRAFT-202500000003`` — twelve
        hex characters, the temporary identifier's shape entire. Re-dating
        read it as an identifier (nothing to re-file) and left it in
        December while the register and the period guard filed the
        document under January: one document, two periods. The identifier
        ends on a letter the register never ends on, so the shape alone
        no longer decides.
        """
        put = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'numbering_format': 'DRAFT-{YEAR}{SEQ:08d}'},
        )
        assert put.status_code == status.HTTP_200_OK, put.text
        draft = _draft_dated(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2025-12-15',
        )
        row = db_session.get(Document, UUID(draft['id']))
        assert row is not None
        row.number = 'DRAFT-202500000003'
        db_session.commit()

        moved = _redate(client, doc_auth_headers, draft['id'], '2026-01-10')

        assert moved['number'].startswith('DRAFT-2026'), moved['number']
        assert moved['number'] != 'DRAFT-202500000003'
