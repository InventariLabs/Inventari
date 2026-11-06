"""A cleared field clears; a field the payload did not carry stays.

The contract backend AGENTS.md §2b calls "named null clears, absent key
leaves alone". `update_document` used to read every field with a blanket
`is not None`, so the two instructions collapsed into one: the screen said
"updated" over a note or a partner that never changed. The same test also
pins the other half — a key the payload did not send must not touch the
column — because a writer that acts on every key it receives would pass the
first test and lose the value the next save never mentioned.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _draft(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    notes: str,
    scheduled_date: str = '2026-04-01',
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'scheduled_date': scheduled_date,
            'notes': notes,
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': '2'}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _put(
    client: TestClient, headers: dict[str, str], doc_id: str, payload: dict[str, Any]
) -> Any:
    return client.put(
        f'/api/v1/warehouse/documents/{doc_id}', headers=headers, json=payload
    )


@pytest.mark.integration
class TestAClearedFieldClearsAndAnAbsentOneStays:
    def test_a_named_null_clears_the_note(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        draft = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            notes='kept for now',
        )

        cleared = _put(client, doc_auth_headers, draft['id'], {'notes': None})

        assert cleared.status_code == status.HTTP_200_OK, cleared.text
        assert cast(dict[str, Any], cleared.json())['notes'] is None

    def test_a_key_the_payload_did_not_carry_leaves_the_note(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The other half: an absent key is not a decision.

        Passing both ways matters — a writer that wrote every field it was
        handed would clear the note here while still clearing it when asked.
        """
        draft = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            notes='kept for now',
        )

        touched = _put(
            client, doc_auth_headers, draft['id'], {'external_reference': 'REF-1'}
        )

        assert touched.status_code == status.HTTP_200_OK, touched.text
        body = cast(dict[str, Any], touched.json())
        assert body['notes'] == 'kept for now'
        assert body['external_reference'] == 'REF-1'

    def test_a_named_null_clears_the_partner_where_none_is_required(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The success half of clearing a partner: an internal receipt takes
        a partner but does not need one, so the named null lands as NULL.

        Passing only the refusal test would let a writer that ignores a
        partner key sent as null stay green; this one fails then, because the
        partner would still be on the document.
        """
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INTERNAL_IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '2',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        draft = cast(dict[str, Any], created.json())
        assert draft['partner_id'] == str(doc_partner.id)

        cleared = _put(client, doc_auth_headers, draft['id'], {'partner_id': None})

        assert cleared.status_code == status.HTTP_200_OK, cleared.text
        assert cast(dict[str, Any], cleared.json())['partner_id'] is None
        kept = client.get(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert cast(dict[str, Any], kept.json())['partner_id'] is None

    def test_a_named_null_on_a_partner_a_receipt_may_not_lose_is_refused_by_name(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A receipt cannot stand without a partner, so the clearing is
        refused with the field named — never written as NULL and left to fail
        at the next step.

        With the partners module off the UI hides the field and create lets a
        receipt stand without one, so update lets it go too (the same rule
        create asks). The refusal this pins is the one the module's own
        organizations ask for, which is why the module is switched on here.
        """
        doc_org.enabled_modules = [*(doc_org.enabled_modules or []), 'partners']
        db_session.add(doc_org)
        db_session.commit()

        draft = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            notes='',
        )

        refused = _put(client, doc_auth_headers, draft['id'], {'partner_id': None})

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'partner_id' in refused.text
        kept = client.get(
            f'/api/v1/warehouse/documents/{draft["id"]}', headers=doc_auth_headers
        )
        assert cast(dict[str, Any], kept.json())['partner_id'] == str(doc_partner.id)

    def test_clearing_the_date_refiles_the_number_where_the_document_now_sits(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The decision on `scheduled_date`: clearing is a date change like
        any other, so the number drawn at confirmation follows the date the
        document then carries (none of its own, which numbers where the
        register looks for it) — not a date the document no longer has.

        Before confirmation there is no number to re-file: the draft holds
        an identifier, and the date travels to confirmation with it.
        """
        draft = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            notes='',
            scheduled_date='2025-12-15',
        )
        assert draft['number'].startswith('DRAFT-')

        cleared = _put(client, doc_auth_headers, draft['id'], {'scheduled_date': None})

        assert cleared.status_code == status.HTTP_200_OK, cleared.text
        body = cast(dict[str, Any], cleared.json())
        assert body['scheduled_date'] is None
        assert body['number'] == draft['number']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{draft["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        number = cast(dict[str, Any], confirmed.json())['number']
        assert not number.startswith('IN/2025/'), (
            'the number still names a period the document no longer carries'
        )
