"""A receipt nobody ordered has no expected quantity to exceed.

The phone saves the receive sheet as a receipt before its item-by-item
sheet opens, and the sheet's row starts at one unit. That figure is a
count somebody typed to get a row, not a promise from a purchase order or
a delivery note, yet the receiving session weighed the count the
storekeeper confirmed against it and refused five of "one expected" as a
surplus past the tolerance. A line marked as a typed count is accepted at
whatever was counted; a line with a real expectation still meets the
tolerance.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _session(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
    **line: Any,
) -> tuple[str, dict[str, Any]]:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 1,
                    **line,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    started = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert started.status_code == 201, started.text
    return str(doc_id), started.json()


def _confirm_count(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    session: dict[str, Any],
    quantity: int,
) -> Any:
    return client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/short-receive',
        headers=headers,
        json={'line_id': session['lines'][0]['id'], 'received_quantity': quantity},
    )


def _stock_at(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
) -> Decimal:
    resp = client.get(
        '/api/v1/stock-quants',
        headers=headers,
        params={
            'product_template_id': str(template.id),
            'location_id': str(location.id),
        },
    )
    assert resp.status_code == 200, resp.text
    return sum((Decimal(row['quantity']) for row in resp.json()['items']), Decimal(0))


def test_the_count_confirmed_on_the_sheet_is_not_a_surplus(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc_id, session = _session(
        client,
        doc_auth_headers,
        doc_partner,
        doc_target_location,
        doc_template,
        expected_is_count=True,
    )

    # One was typed on the first screen; five came.
    resp = _confirm_count(client, doc_auth_headers, doc_id, session, 5)

    assert resp.status_code == 200, resp.text
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
    )
    assert done.status_code == 200, done.text
    assert _stock_at(
        client, doc_auth_headers, doc_template, doc_target_location
    ) == Decimal(5)
    line = done.json()['lines'][0]
    assert Decimal(line['done_quantity']) == Decimal(5)


def test_a_line_with_a_real_expectation_still_meets_the_tolerance(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc_id, session = _session(
        client, doc_auth_headers, doc_partner, doc_target_location, doc_template
    )

    resp = _confirm_count(client, doc_auth_headers, doc_id, session, 5)

    # The test user may receive over tolerance, so the surplus is a question.
    assert resp.status_code == 409, resp.text
    assert resp.json()['detail']['code'] == 'SURPLUS_NEEDS_CONFIRMATION'


def _settled_line(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete', headers=headers
    )
    assert done.status_code == 200, done.text
    line: dict[str, Any] = done.json()['lines'][0]
    return line


def test_a_count_raised_in_the_dialog_is_not_marked_a_surplus(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc_id, session = _session(
        client,
        doc_auth_headers,
        doc_partner,
        doc_target_location,
        doc_template,
        expected_is_count=True,
    )

    resp = _confirm_count(client, doc_auth_headers, doc_id, session, 2)
    assert resp.status_code == 200, resp.text

    line = _settled_line(client, doc_auth_headers, doc_id)
    assert line['discrepancy_code'] is None
    assert line['line_status'] == 'DONE'


def test_a_count_raised_by_scanning_is_not_marked_a_surplus(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc_id, session = _session(
        client,
        doc_auth_headers,
        doc_partner,
        doc_target_location,
        doc_template,
        expected_is_count=True,
    )

    scanned = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/scan',
        headers=doc_auth_headers,
        json={'barcode': doc_template.barcode, 'quantity': '2'},
    )
    assert scanned.status_code == 200, scanned.text

    line = _settled_line(client, doc_auth_headers, doc_id)
    assert line['discrepancy_code'] is None
    assert line['line_status'] == 'DONE'


def test_a_line_with_a_real_expectation_raised_is_still_a_surplus(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc_id, session = _session(
        client, doc_auth_headers, doc_partner, doc_target_location, doc_template
    )

    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/short-receive',
        headers=doc_auth_headers,
        json={'line_id': session['lines'][0]['id'], 'received_quantity': 2},
        params={'confirm_surplus': 'true'},
    )
    assert resp.status_code == 200, resp.text

    line = _settled_line(client, doc_auth_headers, doc_id)
    assert line['discrepancy_code'] == 'SURPLUS'
