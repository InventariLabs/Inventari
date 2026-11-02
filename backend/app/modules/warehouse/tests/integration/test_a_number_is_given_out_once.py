"""A document number is handed out once, and it says when the document is for.

The next number used to be derived by scanning the numbers already taken
and adding one to the highest. A draft deleted the same afternoon dropped
out of that scan, so the next document was handed the number the deleted
one had — against a register whose whole purpose is that a number
identifies one document for good, and against the way every system our
users arrive from does it: Odoo's ir.sequence and ERPNext's Naming Series
both keep a counter that only ever goes up.

Numbering moved to confirmation, which closes the gap at its root — a
draft holds an identifier of its own and never touches the counter — and
the two halves of the old guarantee are asserted here anyway: deletion
changes nothing about the numbers around it, and the number drawn at
confirmation carries the document's own date, not the clock's.

The prefix had the same shape of problem. It was built from the clock, so
a delivery entered on 2 January and dated to the December it belongs to
was filed under January — and the register, which groups by the document's
own date, then disagreed with the number printed on the page.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

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
    scheduled_date: str | None = None,
) -> tuple[str, str]:
    """``(id, number)`` of a fresh draft receipt."""
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
    return cast(str, resp.json()['id']), cast(str, resp.json()['number'])


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> str:
    """The number the document carries once it takes effect."""
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(str, resp.json()['number'])


@pytest.mark.integration
class TestANumberIsGivenOutOnce:
    def test_a_deleted_draft_leaves_the_series_where_it_stands(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        first_id, _ = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        first = _confirm(client, doc_auth_headers, first_id)
        assert first.endswith('/001'), first

        # A plan written and thrown away between two documents: it held no
        # number, so the register neither skips nor repeats anything.
        throwaway_id, _ = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        deleted = client.delete(
            f'/api/v1/warehouse/documents/{throwaway_id}', headers=doc_auth_headers
        )
        assert deleted.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        ), deleted.text

        second_id, _ = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )
        second = _confirm(client, doc_auth_headers, second_id)
        assert second.endswith('/002'), second

    def test_a_backdated_document_is_filed_under_its_own_year(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, identifier = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2019-12-15',
        )
        # Nothing of the period shows before the document takes effect —
        # the draft carries an identifier, and the date is what the number
        # will be drawn from.
        assert identifier.startswith('DRAFT-')

        number = _confirm(client, doc_auth_headers, doc_id)

        assert '2019' in number, number

    def test_a_document_with_no_date_of_its_own_is_filed_under_today(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The control: nothing changes for the ordinary document."""
        from datetime import UTC, datetime

        doc_id, _ = _draft(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
        )

        number = _confirm(client, doc_auth_headers, doc_id)

        assert str(datetime.now(UTC).year) in number, number
