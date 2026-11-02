"""One range of dates names the same documents on the list and in the register.

The register files a document under the date it is for. The plain list
filtered and sorted by ``created_at`` — the moment somebody typed the
document in — so the same range asked of the two gave two different sets,
and an auditor comparing them found a disagreement with no explanation.
The module now has one date: the document's own, with the moment of entry
only breaking ties.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

from .test_the_register_reads_the_document_date import _completed_receipt, _rows

LAST_DECEMBER = '2025-12-31'


def _listed(client: TestClient, headers: dict[str, str], **params: Any) -> list[str]:
    resp = client.get('/api/v1/warehouse/documents', headers=headers, params=params)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return [cast(str, row['number']) for row in resp.json()['items']]


@pytest.mark.integration
class TestTheListAndTheRegisterAgreeOnTheDate:
    def test_a_range_names_the_same_documents_on_both(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Entered today, dated to last December: December on both pages."""
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=LAST_DECEMBER,
        )
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=datetime.now(UTC).date().isoformat(),
        )

        listed = _listed(
            client, doc_auth_headers, date_from='2025-12-01', date_to=LAST_DECEMBER
        )
        registered = [
            cast(str, row['number'])
            for row in _rows(
                client,
                doc_auth_headers,
                date_from='2025-12-01',
                date_to=LAST_DECEMBER,
                group_key='IN',
            )
        ]

        assert len(listed) == 1
        assert listed == registered

    def test_newest_first_is_by_the_documents_own_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """The backdated one was typed in last, and still sorts last."""
        today = datetime.now(UTC).date().isoformat()
        current = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=today,
        )
        backdated = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=LAST_DECEMBER,
        )
        ids = [
            row['id']
            for row in client.get(
                '/api/v1/warehouse/documents', headers=doc_auth_headers
            ).json()['items']
        ]
        assert ids.index(current) < ids.index(backdated)
