"""The register files a document under the date the document is about.

Two ideas of "the document's date" lived in one module. The period guard and
the cost layers read ``scheduled_date`` — the date the document is for. The
register filtered, grouped and displayed ``created_at`` — the moment somebody
typed it in.

A delivery entered on 2 January and dated to 31 December then belonged to
December as far as closing the books went, and to January as far as the
register was concerned. Whichever of the two a warehouse trusted, the other
one disagreed, and the numbering printed on the page was a third answer
again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _completed_receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    scheduled_date: str,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'scheduled_date': scheduled_date,
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': '2',
                    'unit_price': '5.00',
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    assert (
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        ).status_code
        == status.HTTP_200_OK
    )
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def _register(
    client: TestClient, headers: dict[str, str], *, date_from: str, date_to: str
) -> dict[str, Any]:
    resp = client.get(
        '/api/v1/warehouse/register/summary',
        headers=headers,
        params={'date_from': date_from, 'date_to': date_to},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _rows(
    client: TestClient,
    headers: dict[str, str],
    *,
    date_from: str,
    date_to: str,
    group_key: str,
) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/warehouse/register/rows',
        headers=headers,
        params={
            'date_from': date_from,
            'date_to': date_to,
            'group_by': 'type',
            'group_key': group_key,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, Any]], resp.json()['items'])


@pytest.mark.integration
class TestTheRegisterReadsTheDocumentDate:
    def test_a_backdated_document_falls_in_its_own_window(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        back_then = (datetime.now(UTC).date() - timedelta(days=45)).isoformat()
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=back_then,
        )

        found = _register(
            client, doc_auth_headers, date_from=back_then, date_to=back_then
        )
        assert found['summary']['total_documents'] == 1, found

    def test_it_is_not_also_in_the_window_it_was_typed_in(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        today = datetime.now(UTC).date()
        back_then = (today - timedelta(days=45)).isoformat()
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=back_then,
        )

        now = _register(
            client,
            doc_auth_headers,
            date_from=today.isoformat(),
            date_to=today.isoformat(),
        )
        assert now['summary']['total_documents'] == 0, now

    def test_the_row_shows_the_date_it_was_filed_under(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        back_then = (datetime.now(UTC).date() - timedelta(days=45)).isoformat()
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=back_then,
        )
        found = _register(
            client, doc_auth_headers, date_from=back_then, date_to=back_then
        )
        assert found['summary']['total_documents'] == 1, found
        rows = _rows(
            client,
            doc_auth_headers,
            date_from=back_then,
            date_to=back_then,
            group_key='IN',
        )
        assert len(rows) == 1, rows
        assert rows[0]['date'].startswith(back_then), rows[0]

    def test_a_document_with_no_date_of_its_own_still_files_under_today(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The control: the ordinary document is where it always was."""
        today = datetime.now(UTC).date().isoformat()
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
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
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        found = _register(client, doc_auth_headers, date_from=today, date_to=today)
        assert found['summary']['total_documents'] == 1, found
