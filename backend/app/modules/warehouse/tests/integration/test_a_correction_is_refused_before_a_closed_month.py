"""A correction is refused at the door of a closed month, not left stuck.

A correction carries no editable date — its period is the day it was written —
so a draft created in a month that closes can never be applied, and the
refusal that told the reader to change a document date named a field its
screen does not offer. Creation now asks the period guard first, with a
sentence that offers the only way out there is: reopening the month.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

API = '/api/v1/warehouse'


def _period_of_today() -> tuple[int, int]:
    now = datetime.now(UTC)
    return now.year, now.month


def _close_the_month(client: TestClient, headers: dict[str, str]) -> None:
    year, month = _period_of_today()
    closed = client.post(f'{API}/periods/{year}/{month}/close', headers=headers)
    assert closed.status_code == status.HTTP_200_OK, closed.text


def _a_completed_receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    template: ProductTemplate,
) -> dict[str, Any]:
    created = client.post(
        f'{API}/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 5,
                    'done_quantity': 5,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(f'{API}/documents/{doc_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'{API}/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    return cast(dict[str, Any], created.json())


def _a_correction_body(original_id: str) -> dict[str, Any]:
    return {
        'corrects_document_id': original_id,
        'reason_code': 'WRONG_QUANTITY',
        'lines': [{'original_line_number': 1, 'quantity_delta': -1}],
    }


def _refusal_message(response: Any) -> str:
    detail = response.json()['detail']
    assert detail['code'] == 'PERIOD_CLOSED'
    return str(detail['message'])


@pytest.mark.integration
class TestACorrectionAndAClosedMonth:
    def test_creating_one_in_a_closed_month_writes_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        receipt = _a_completed_receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
        )
        _close_the_month(client, doc_auth_headers)

        documents_before = db_session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == doc_org.id)
        )
        refused = client.post(
            f'{API}/corrections',
            headers=doc_auth_headers,
            json=_a_correction_body(receipt['id']),
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        message = _refusal_message(refused).lower()
        # The correction screen has no date to change; the only way out is the
        # month being reopened, and the sentence says that and nothing else.
        assert 'change the document date' not in message
        assert 'reopen' in message
        db_session.expire_all()
        documents_after = db_session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == doc_org.id)
        )
        assert documents_after == documents_before

    def test_applying_one_whose_month_closed_says_how_to_get_out(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        receipt = _a_completed_receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
        )
        created = client.post(
            f'{API}/corrections',
            headers=doc_auth_headers,
            json=_a_correction_body(receipt['id']),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction_id = created.json()['id']

        _close_the_month(client, doc_auth_headers)
        refused = client.patch(
            f'{API}/documents/{correction_id}/confirm', headers=doc_auth_headers
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        message = _refusal_message(refused).lower()
        assert 'change the document date' not in message
        assert 'reopen' in message
