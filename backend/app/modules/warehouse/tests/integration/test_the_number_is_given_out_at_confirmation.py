"""The number is given out when the draft is confirmed, not before.

Numbering a draft spent a number on every plan: the drafts deleted the
same afternoon left gaps in the register, and the order of the numbers
was the order in which people started writing rather than the order in
which the documents took effect. A draft is not a paper yet, so it
carries a temporary identifier of its own, and the number — the one the
register, the binder and the search know — is drawn when the draft is
confirmed, in the period the document's own date names.

Which leaves the two halves of the old rule standing on their own: a
draft is still deletable (it never had a number, so deleting it burns
nothing), while a cancelled document keeps the number it was given and
cannot be deleted — the number is the evidence, and erasing the document
erases it.
"""

from __future__ import annotations

import re
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


def _create_draft(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    scheduled_date: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'type': 'IN',
        'partner_id': str(partner_id),
        'target_location_id': str(location_id),
        'lines': [{'product_template_id': str(template_id), 'expected_quantity': '1'}],
    }
    if scheduled_date is not None:
        body['scheduled_date'] = scheduled_date
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _confirm(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _cancel(client: TestClient, headers: dict[str, str], doc_id: str) -> dict[str, Any]:
    resp = client.patch(f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestADraftCarriesATemporaryIdentifier:
    def test_a_draft_is_numbered_with_an_identifier_of_its_own(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        first = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        second = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )

        for draft in (first, second):
            assert draft['number'].startswith('DRAFT-'), draft['number']
            # Not a number of the register's series: no type code, no
            # period, no sequence — nothing a reader could mistake for
            # a document that took effect.
            assert '/' not in draft['number'], draft['number']
        assert first['number'] != second['number']

    def test_drafts_take_no_number_from_the_series(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The defect this replaces: a draft used to spend a sequence number.

        Three drafts written and thrown away left IN/2026/001 through
        003 gone from the register. Deletion cannot give a number back
        now, because no draft ever held one.
        """
        for _ in range(3):
            draft = _create_draft(
                client,
                doc_auth_headers,
                partner_id=doc_partner.id,
                location_id=doc_target_location.id,
                template_id=doc_template.id,
            )
            deleted = client.delete(
                f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
            )
            assert deleted.status_code in (
                status.HTTP_200_OK,
                status.HTTP_204_NO_CONTENT,
            ), deleted.text

        survivor = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        confirmed = _confirm(client, doc_auth_headers, survivor['id'])

        assert re.fullmatch(r'IN/\d{4}/001', confirmed['number']), confirmed['number']


@pytest.mark.integration
class TestTheNumberIsDrawnAtConfirmation:
    def test_confirmation_replaces_the_identifier_with_the_number(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        assert draft['number'].startswith('DRAFT-')

        confirmed = _confirm(client, doc_auth_headers, draft['id'])

        assert confirmed['status'] == 'CONFIRMED'
        assert re.fullmatch(r'IN/\d{4}/001', confirmed['number']), confirmed['number']

    def test_a_draft_whose_issued_number_begins_with_draft_keeps_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A number the format itself printed ``DRAFT-`` on is still a number.

        ``DRAFT-{TYPE}/{YEAR}/{SEQ:03d}`` is a legal profile format, so a
        draft numbered before numbering moved to confirmation can carry
        ``DRAFT-IN/2026/0003`` as an issued number of the register.
        Confirmation read the format's own prefix as the temporary
        identifier and drew a second number — 0004 — leaving one document
        with two numbers and the register with a hole where 0003 stood
        differently than the paper said.
        """
        client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'numbering_format': 'DRAFT-{TYPE}/{YEAR}/{SEQ:03d}'},
        )
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        row = db_session.get(Document, UUID(draft['id']))
        assert row is not None
        row.number = 'DRAFT-IN/2026/0003'
        db_session.commit()

        confirmed = _confirm(client, doc_auth_headers, draft['id'])

        assert confirmed['number'] == 'DRAFT-IN/2026/0003', confirmed['number']

    def test_a_draft_whose_issued_number_is_the_identifiers_whole_shape_keeps_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """An issued number in the identifier's whole shape is still its own.

        ``DRAFT-000000000{SEQ:03d}`` is a legal profile format and prints
        ``DRAFT-000000000003`` — twelve hex characters, the temporary
        identifier's shape entire. Reading that shape as an identifier
        drew a second number over a number the register had already
        issued: one document with two numbers, and a hole where the
        first one stood. The identifier ends on a letter the register
        never ends on, so the shape alone is no longer what decides.
        """
        put = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'numbering_format': 'DRAFT-000000000{SEQ:03d}', 'number_padding': 3},
        )
        assert put.status_code == status.HTTP_200_OK, put.text
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        row = db_session.get(Document, UUID(draft['id']))
        assert row is not None
        row.number = 'DRAFT-000000000003'
        db_session.commit()

        confirmed = _confirm(client, doc_auth_headers, draft['id'])

        assert confirmed['number'] == 'DRAFT-000000000003', confirmed['number']

    def test_a_backdated_draft_is_numbered_in_its_own_period(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The number carries the document's own date, not the clock's."""
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2019-12-15',
        )
        assert draft['number'].startswith('DRAFT-')

        confirmed = _confirm(client, doc_auth_headers, draft['id'])

        assert confirmed['number'].startswith('IN/2019/'), confirmed['number']

    def test_a_refused_confirmation_keeps_the_draft_on_its_identifier(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
    ) -> None:
        """A confirmation the server refuses draws nothing.

        A write-off whose line names only the catalogue entry is refused
        at confirmation — the document commits there, so that is where the
        refusal stands. The identifier it carries comes out of the refusal
        unchanged, and the series never heard about it.
        """
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        draft = cast(dict[str, Any], created.json())
        assert draft['number'].startswith('DRAFT-')

        refused = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

        reread = client.get(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert reread.status_code == status.HTTP_200_OK, reread.text
        assert reread.json()['number'] == draft['number']


@pytest.mark.integration
class TestACancelledDocumentKeepsItsNumberAndStands:
    def test_a_cancelled_document_keeps_the_number_it_was_given(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        confirmed = _confirm(client, doc_auth_headers, draft['id'])
        number = confirmed['number']

        cancelled = _cancel(client, doc_auth_headers, draft['id'])

        assert cancelled['status'] == 'CANCELLED'
        assert cancelled['number'] == number

    def test_a_cancelled_document_cannot_be_deleted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The number is the record of an act that happened; the row keeps it.

        Deleting a cancelled document erased the paper that carried a
        number out of the books — a hole in the register with nothing
        left to explain it.
        """
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        _confirm(client, doc_auth_headers, draft['id'])
        _cancel(client, doc_auth_headers, draft['id'])

        deleted = client.delete(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )

        assert deleted.status_code == status.HTTP_400_BAD_REQUEST, deleted.text
        still_there = client.get(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert still_there.status_code == status.HTTP_200_OK

    def test_a_draft_is_still_deletable(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The control: a plan nobody confirmed is nobody's evidence."""
        draft = _create_draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )

        deleted = client.delete(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )

        assert deleted.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        ), deleted.text
