"""Completing a receipt asks for the expiry a FEFO product's line lacks.

The scan and the tap doors ask the lot-and-expiry question before booking a
quantity, but the completion endpoint reaches the stock executor directly.
A confirmed receipt completed through it with per-line quantities put a
FEFO product on the shelf undated, where it sorts behind every dated record
of itself.

The completion now refuses such a line through ``RECEIPT_EXPIRY_REQUIRED``,
naming every undated line, and records nothing. The call sent again with
the lot and expiry carries them onto the document line exactly as a
receiving scan's do, and the stock record the delivery opens is dated.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.approvals.models import ApprovalRequest
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.tests.integration._records import sow
from app.modules.warehouse.tests.integration.test_the_one_step_action_posts_whole import (
    _set_threshold,
)
from app.modules.warehouse.tests.integration.test_wms_receiving import (
    _confirm_document,
    _create_in_document,
)

pytestmark = pytest.mark.integration

EXPIRY = date(2027, 5, 20)


def _confirmed_receipt(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    *,
    quantity: int = 2,
    expiry_date: date | None = None,
) -> str:
    if expiry_date is None:
        doc_id = _create_in_document(
            client, headers, location.id, partner.id, template.id, quantity=quantity
        )
    else:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'IN',
                'partner_id': str(partner.id),
                'target_location_id': str(location.id),
                'lines': [
                    {
                        'product_template_id': str(template.id),
                        'expected_quantity': quantity,
                        'expiry_date': expiry_date.isoformat(),
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
    _confirm_document(client, headers, doc_id)
    return doc_id


def _line_of(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    resp = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    lines: list[dict[str, Any]] = resp.json()['lines']
    assert len(lines) == 1
    return lines[0]


def _complete(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    line_id: str,
    **extra: Any,
) -> Any:
    return client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={
            'lines': [
                {'line_id': line_id, 'done_quantity': 2, **extra},
            ]
        },
    )


@pytest.fixture
def fefo_template(
    db_session: Session, doc_template: ProductTemplate
) -> ProductTemplate:
    doc_template.removal_strategy = 'FEFO'
    db_session.commit()
    return doc_template


class TestTheCompletionAsksForTheExpiry:
    def test_a_fefo_line_without_a_date_is_refused_and_nothing_is_posted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, fefo_template
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        refused = _complete(client, doc_auth_headers, doc_id, line['id'])

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        detail = refused.json()['detail']
        assert detail['code'] == 'RECEIPT_EXPIRY_REQUIRED'
        assert detail['lines'] == [
            {
                'line_id': line['id'],
                'line_number': line['line_number'],
                'product': line['name'],
            }
        ]
        still_open = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert still_open.json()['status'] == 'CONFIRMED'
        db_session.expire_all()
        assert (
            db_session.scalars(
                select(Item).where(Item.template_id == fefo_template.id)
            ).all()
            == []
        )

    def test_the_completion_sent_again_with_lot_and_expiry_dates_the_line_and_the_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, fefo_template
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        completed = _complete(
            client,
            doc_auth_headers,
            doc_id,
            line['id'],
            batch_number='LOT-C1',
            expiry_date=EXPIRY.isoformat(),
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        dated = _line_of(client, doc_auth_headers, doc_id)
        assert dated['batch_number'] == 'LOT-C1'
        assert dated['expiry_date'] == EXPIRY.isoformat()

        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).one()
        assert item.expiry_date == EXPIRY
        lot = db_session.get(StockLot, cast(uuid.UUID, item.lot_id))
        assert lot is not None
        assert lot.name == 'LOT-C1'
        assert lot.expiry_date == EXPIRY

    def test_a_line_that_already_names_its_expiry_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _confirmed_receipt(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            fefo_template,
            expiry_date=EXPIRY,
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        completed = _complete(client, doc_auth_headers, doc_id, line['id'])

        assert completed.status_code == status.HTTP_200_OK, completed.text
        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).one()
        assert item.expiry_date == EXPIRY

    def test_a_line_that_brings_nothing_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, fefo_template
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line['id'],
                        'done_quantity': 0,
                        'discrepancy_code': 'SHORTAGE',
                    }
                ]
            },
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text

    def test_a_line_naming_only_a_fefo_record_is_asked_through_its_template(
        self,
        client: TestClient,
        async_engine_fixture: AsyncEngine,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A receipt line may name the record it receives into instead of the
        product; the record's template is the one that says FEFO."""
        record = sow(
            db_session,
            async_engine_fixture,
            doc_org,
            fefo_template,
            doc_target_location.id,
            2,
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])
        _confirm_document(client, doc_auth_headers, doc_id)
        line = _line_of(client, doc_auth_headers, doc_id)
        assert line['product_template_id'] is None

        refused = _complete(client, doc_auth_headers, doc_id, line['id'])

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert refused.json()['detail']['code'] == 'RECEIPT_EXPIRY_REQUIRED'
        assert refused.json()['detail']['lines'] == [
            {
                'line_id': line['id'],
                'line_number': line['line_number'],
                'product': line['name'],
            }
        ]
        still_open = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert still_open.json()['status'] == 'CONFIRMED'

        completed = _complete(
            client,
            doc_auth_headers,
            doc_id,
            line['id'],
            batch_number='LOT-R1',
            expiry_date=EXPIRY.isoformat(),
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        dated = _line_of(client, doc_auth_headers, doc_id)
        assert dated['batch_number'] == 'LOT-R1'
        assert dated['expiry_date'] == EXPIRY.isoformat()
        db_session.expire_all()
        records = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).all()
        received = next(record for record in records if record.expiry_date == EXPIRY)
        assert received.quantity == 2
        lot = db_session.get(StockLot, cast(uuid.UUID, received.lot_id))
        assert lot is not None
        assert lot.name == 'LOT-R1'

    def test_a_product_without_a_removal_strategy_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        completed = _complete(client, doc_auth_headers, doc_id, line['id'])

        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert _line_of(client, doc_auth_headers, doc_id)['expiry_date'] is None


class TestTheOneStepPostingAsksToo:
    """A draft posted in one press books its lines as planned, so the only
    answer it can carry is the lot and expiry the question collected."""

    def test_posting_a_fefo_draft_without_a_date_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            fefo_template.id,
            quantity=2,
        )

        refused = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert refused.json()['detail']['code'] == 'RECEIPT_EXPIRY_REQUIRED'
        still_a_draft = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert still_a_draft.json()['status'] == 'DRAFT'
        db_session.expire_all()
        assert (
            db_session.scalars(
                select(Item).where(Item.template_id == fefo_template.id)
            ).all()
            == []
        )

    def test_the_posting_sent_again_with_them_dates_the_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _create_in_document(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            fefo_template.id,
            quantity=2,
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        completed = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line['id'],
                        'batch_number': 'LOT-P1',
                        'expiry_date': EXPIRY.isoformat(),
                    }
                ]
            },
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert completed.json()['status'] == 'COMPLETED'
        dated = _line_of(client, doc_auth_headers, doc_id)
        assert dated['batch_number'] == 'LOT-P1'
        assert dated['expiry_date'] == EXPIRY.isoformat()
        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).one()
        assert item.expiry_date == EXPIRY


def _receipt_draft_over_the_limit(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    *,
    quantity: int = 2,
) -> str:
    """A receipt draft of *template* worth more than the approval limit set."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                    'unit_price': '10.00',
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


class TestTheOneStepPostingBehindAnApproval:
    """A FEFO draft posted in one press that the profile sends for approval.

    The approval is the door that completes the document, and the approver is
    not the person holding the pack. The lot and expiry are asked at the
    press, where the reader is, and stay on the lines the approval posts.
    """

    def test_the_press_asks_before_the_approval_takes_the_document(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        doc_approval_workflow: Any,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        doc_id = _receipt_draft_over_the_limit(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            fefo_template,
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        refused = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        detail = refused.json()['detail']
        assert detail['code'] == 'RECEIPT_EXPIRY_REQUIRED'
        assert detail['lines'] == [
            {
                'line_id': line['id'],
                'line_number': line['line_number'],
                'product': line['name'],
            }
        ]
        still_a_draft = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert still_a_draft.json()['status'] == 'DRAFT'
        db_session.expire_all()
        assert db_session.scalars(select(ApprovalRequest)).all() == []
        assert (
            db_session.scalars(
                select(Item).where(Item.template_id == fefo_template.id)
            ).all()
            == []
        )

    def test_the_answer_rides_into_the_parked_lines_and_the_approval_posts_them_dated(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        doc_approval_workflow: Any,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        doc_id = _receipt_draft_over_the_limit(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            fefo_template,
        )
        line = _line_of(client, doc_auth_headers, doc_id)

        parked = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post',
            headers=doc_auth_headers,
            json={
                'lines': [
                    {
                        'line_id': line['id'],
                        'batch_number': 'LOT-A1',
                        'expiry_date': EXPIRY.isoformat(),
                    }
                ]
            },
        )

        assert parked.status_code == status.HTTP_200_OK, parked.text
        assert parked.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
        dated = _line_of(client, doc_auth_headers, doc_id)
        assert dated['batch_number'] == 'LOT-A1'
        assert dated['expiry_date'] == EXPIRY.isoformat()
        db_session.expire_all()
        # Nothing moved while the approval stood in the way.
        assert (
            db_session.scalars(
                select(Item).where(Item.template_id == fefo_template.id)
            ).all()
            == []
        )

        approved = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        db_session.expire_all()
        finished = db_session.get(Document, uuid.UUID(doc_id))
        assert finished is not None
        assert finished.status == DocumentStatus.COMPLETED.value
        received = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).one()
        assert received.expiry_date == EXPIRY
        lot = db_session.get(StockLot, cast(uuid.UUID, received.lot_id))
        assert lot is not None
        assert lot.name == 'LOT-A1'

    def test_a_draft_of_a_product_that_is_not_taken_by_expiry_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_approval_workflow: Any,
    ) -> None:
        _set_threshold(client, doc_auth_headers, '1.00')
        doc_id = _receipt_draft_over_the_limit(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
        )

        parked = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert parked.status_code == status.HTTP_200_OK, parked.text
        assert parked.json()['status'] == DocumentStatus.PENDING_APPROVAL.value
