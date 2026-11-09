"""A return is a draft like any other, so it can be copied like any other.

Its reason is a return's own code (NOT_NEEDED is not a scrap reason), which
the create schema of a scrap refused: duplicating a return answered 400.

A copy is still a return of the same receipt: it names the receipt and takes
its goods out of what is left to return, as the return it was copied from
does — and so does a return saved from the edit form. A copy written as an
ordinary document let returns add up past what the receipt brought in.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

API = '/api/v1/warehouse'


def _completed_receipt(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    line: dict[str, Any],
) -> str:
    received = client.post(
        f'{API}/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [line],
        },
    )
    assert received.status_code == status.HTTP_201_CREATED, received.text
    receipt_id = cast(str, received.json()['id'])
    confirmed = client.patch(f'{API}/documents/{receipt_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'{API}/documents/{receipt_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    return receipt_id


def _return(
    client: TestClient, headers: dict[str, str], receipt_id: str, quantity: str
) -> Any:
    return client.post(
        f'{API}/documents/{receipt_id}/return',
        headers=headers,
        json={
            'reason_code': 'NOT_NEEDED',
            'lines': [{'original_line_number': 1, 'return_quantity': quantity}],
        },
    )


@pytest.mark.integration
def test_a_return_is_duplicated_with_its_reason_and_partner(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    original_id = _completed_receipt(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        {'product_template_id': str(doc_template.id), 'expected_quantity': '5'},
    )
    returned = _return(client, doc_auth_headers, original_id, '2')
    assert returned.status_code == status.HTTP_201_CREATED, returned.text

    copy = client.post(
        f'{API}/documents/{returned.json()["id"]}/duplicate',
        headers=doc_auth_headers,
    )

    assert copy.status_code == status.HTTP_201_CREATED, copy.text
    body = copy.json()
    assert body['reason_code'] == 'NOT_NEEDED'
    assert body['partner_id'] == str(doc_partner.id)
    assert body['status'] == 'DRAFT'


@pytest.mark.integration
def test_a_copy_of_a_return_names_the_receipt_and_counts_against_it(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    receipt_id = _completed_receipt(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        {'product_template_id': str(doc_template.id), 'expected_quantity': '20'},
    )
    returned = _return(client, doc_auth_headers, receipt_id, '2')
    assert returned.status_code == status.HTTP_201_CREATED, returned.text

    copy = client.post(
        f'{API}/documents/{returned.json()["id"]}/duplicate',
        headers=doc_auth_headers,
    )
    assert copy.status_code == status.HTTP_201_CREATED, copy.text

    read = client.get(f'{API}/documents/{copy.json()["id"]}', headers=doc_auth_headers)
    assert read.json()['return_of_id'] == receipt_id
    # Two returns of 2 leave 16 of the 20 received.
    beyond = _return(client, doc_auth_headers, receipt_id, '17')
    assert beyond.status_code == status.HTTP_400_BAD_REQUEST, beyond.text
    assert '(16 of 20)' in beyond.json()['detail']['message']
    assert _return(client, doc_auth_headers, receipt_id, '16').status_code == (
        status.HTTP_201_CREATED
    )


@pytest.mark.integration
def test_a_copy_of_a_return_is_refused_past_what_is_left(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    receipt_id = _completed_receipt(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        {'product_template_id': str(doc_template.id), 'expected_quantity': '5'},
    )
    returned = _return(client, doc_auth_headers, receipt_id, '3')
    assert returned.status_code == status.HTTP_201_CREATED, returned.text

    copy = client.post(
        f'{API}/documents/{returned.json()["id"]}/duplicate',
        headers=doc_auth_headers,
    )

    assert copy.status_code == status.HTTP_400_BAD_REQUEST, copy.text
    assert copy.json()['detail']['message'] == (
        'A return of 3 is more than what is left of line 1 (2 of 5)'
    )


@pytest.mark.integration
def test_a_return_saved_from_the_edit_form_still_counts_against_its_receipt(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    receipt_id = _completed_receipt(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        {'product_template_id': str(doc_template.id), 'expected_quantity': '20'},
    )
    returned = _return(client, doc_auth_headers, receipt_id, '2')
    assert returned.status_code == status.HTTP_201_CREATED, returned.text
    line = returned.json()['lines'][0]

    # The form sends every line back, as it holds them, with the new count.
    edited = client.put(
        f'{API}/documents/{returned.json()["id"]}',
        headers=doc_auth_headers,
        json={
            'partner_id': str(doc_partner.id),
            'lines': [
                {
                    'item_id': line['item_id'],
                    'product_template_id': line['product_template_id'],
                    'expected_quantity': '5',
                }
            ],
        },
    )
    assert edited.status_code == status.HTTP_200_OK, edited.text

    beyond = _return(client, doc_auth_headers, receipt_id, '16')
    assert beyond.status_code == status.HTTP_400_BAD_REQUEST, beyond.text
    assert '(15 of 20)' in beyond.json()['detail']['message']
    too_many = client.put(
        f'{API}/documents/{returned.json()["id"]}',
        headers=doc_auth_headers,
        json={
            'lines': [
                {
                    'item_id': line['item_id'],
                    'product_template_id': line['product_template_id'],
                    'expected_quantity': '21',
                }
            ],
        },
    )
    assert too_many.status_code == status.HTTP_400_BAD_REQUEST, too_many.text
    assert too_many.json()['detail']['message'] == (
        'A return of 21 is more than what is left of line 1 (20 of 20)'
    )


@pytest.mark.integration
def test_a_correction_is_not_duplicated_and_says_why(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    doc_partner: Partner,
) -> None:
    receipt_id = _completed_receipt(
        client,
        doc_auth_headers,
        doc_target_location,
        doc_partner,
        {'product_template_id': str(doc_template.id), 'expected_quantity': '5'},
    )
    corrected = client.post(
        f'{API}/corrections',
        headers=doc_auth_headers,
        json={
            'corrects_document_id': receipt_id,
            'reason_code': 'DATA_ENTRY_ERROR',
            'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
        },
    )
    assert corrected.status_code == status.HTTP_201_CREATED, corrected.text

    copy = client.post(
        f'{API}/documents/{corrected.json()["id"]}/duplicate',
        headers=doc_auth_headers,
    )

    assert copy.status_code == status.HTTP_400_BAD_REQUEST, copy.text
    assert copy.json()['detail']['message'] == (
        'A correction cannot be duplicated: it restates one document. '
        'Write a new correction of that document instead.'
    )


@pytest.mark.integration
def test_a_receipt_line_naming_only_a_record_is_copied_with_it(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
) -> None:
    drafted = client.post(
        f'{API}/documents',
        headers=doc_auth_headers,
        json={
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [{'item_id': str(doc_item.id), 'expected_quantity': '3'}],
        },
    )
    assert drafted.status_code == status.HTTP_201_CREATED, drafted.text

    copy = client.post(
        f'{API}/documents/{drafted.json()["id"]}/duplicate', headers=doc_auth_headers
    )
    assert copy.status_code == status.HTTP_201_CREATED, copy.text
    assert copy.json()['lines'][0]['item_id'] == str(doc_item.id)

    confirmed = client.patch(
        f'{API}/documents/{copy.json()["id"]}/confirm', headers=doc_auth_headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
