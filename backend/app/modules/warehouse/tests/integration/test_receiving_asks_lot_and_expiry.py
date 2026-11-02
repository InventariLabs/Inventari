"""A receiving scan asks for lot and expiry when the product tracks them.

A scan carries a code and a quantity, so a FEFO product used to arrive on
the shelf with no date: the lot and expiry existed only if somebody typed
them on the document beforehand, and under FEFO undated stock sorts last.
The first scan of such a line now answers ``needs_lot_expiry`` and records
nothing; the same scan sent again with the values attaches them to the line,
and completing the document puts them on the stock record the delivery opens.

The tap doors - "Receive full amount" and the short-receive sheet - book a
quantity without a scan, and they ask the same question the same way.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.tests.integration._records import sow
from app.modules.warehouse.tests.integration.test_wms_receiving import (
    _confirm_document,
    _create_in_document,
)
from app.services._stock_draw import plan_draw_async
from tests.integration._shelf import run_in_async_session

pytestmark = pytest.mark.integration

EXPIRY = date(2027, 3, 31)


def _start_session(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
) -> str:
    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    return cast(str, start.json()['id'])


def _scan(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    session_id: str,
    template: ProductTemplate,
    **extra: Any,
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
        headers=headers,
        json={'barcode': template.barcode, 'quantity': '2', **extra},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _confirmed_receipt(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    quantity: int = 5,
) -> str:
    doc_id = _create_in_document(
        client, headers, location.id, partner.id, template.id, quantity=quantity
    )
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


@pytest.fixture
def fefo_template(
    db_session: Session, doc_template: ProductTemplate
) -> ProductTemplate:
    doc_template.removal_strategy = 'FEFO'
    db_session.commit()
    return doc_template


class TestTheFirstScanOfADatedProductAsks:
    def test_a_fefo_product_without_a_date_is_asked_for_one_and_nothing_is_recorded(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)

        answer = _scan(client, doc_auth_headers, doc_id, session_id, fefo_template)

        assert answer['status'] == 'needs_lot_expiry'
        assert answer['line_id'] is not None
        assert answer['received_quantity'] == 0
        session = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}',
            headers=doc_auth_headers,
        ).json()
        assert session['lines'][0]['received_quantity'] == 0
        assert session['lines'][0]['status'] == 'pending'

    def test_the_scan_sent_again_with_lot_and_expiry_records_both_on_the_line(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)

        answer = _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            batch_number='LOT-A1',
            expiry_date=EXPIRY.isoformat(),
        )

        assert answer['status'] == 'received'
        assert answer['received_quantity'] == 2.0
        line = _line_of(client, doc_auth_headers, doc_id)
        assert line['batch_number'] == 'LOT-A1'
        assert line['expiry_date'] == EXPIRY.isoformat()

    def test_the_next_scan_of_the_same_line_does_not_ask_again(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            batch_number='LOT-A1',
            expiry_date=EXPIRY.isoformat(),
        )

        second = _scan(client, doc_auth_headers, doc_id, session_id, fefo_template)

        assert second['status'] == 'received'
        assert second['received_quantity'] == 4.0

    def test_a_product_without_tracking_is_received_as_before(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)

        answer = _scan(client, doc_auth_headers, doc_id, session_id, doc_template)

        assert answer['status'] == 'received'
        line = _line_of(client, doc_auth_headers, doc_id)
        assert line['batch_number'] is None
        assert line['expiry_date'] is None

    def test_a_line_that_already_names_its_expiry_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(fefo_template.id),
                        'expected_quantity': 5,
                        'expiry_date': EXPIRY.isoformat(),
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        _confirm_document(client, doc_auth_headers, doc_id)
        session_id = _start_session(client, doc_auth_headers, doc_id)

        answer = _scan(client, doc_auth_headers, doc_id, session_id, fefo_template)

        assert answer['status'] == 'received'

    def test_a_refused_scan_leaves_the_values_off_the_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The document left CONFIRMED after the session opened, so the
        server refuses the scan; the lot and expiry that rode along with
        it must not be kept."""
        doc_id = _confirmed_receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, fefo_template
        )
        session_id = _start_session(client, doc_auth_headers, doc_id)
        db_session.execute(
            update(Document)
            .where(Document.id == uuid.UUID(doc_id))
            .values(status=DocumentStatus.CANCELLED.value)
        )
        db_session.commit()

        answer = _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            batch_number='LOT-X',
            expiry_date=EXPIRY.isoformat(),
        )

        assert answer['status'] == 'rejected'
        line = _line_of(client, doc_auth_headers, doc_id)
        assert line['batch_number'] is None
        assert line['expiry_date'] is None


def _short_receive(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    session_id: str,
    line_id: str,
    quantity: float,
    **extra: Any,
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
        headers=headers,
        json={'line_id': line_id, 'received_quantity': quantity, **extra},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _session_line(
    client: TestClient, headers: dict[str, str], doc_id: str, session_id: str
) -> dict[str, Any]:
    session = client.get(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}', headers=headers
    ).json()
    return cast(dict[str, Any], session['lines'][0])


class TestTheTapDoorsAskToo:
    def test_receiving_a_fefo_line_in_full_asks_and_records_nothing(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        line = _session_line(client, doc_auth_headers, doc_id, session_id)

        answer = _short_receive(
            client, doc_auth_headers, doc_id, session_id, line['id'], 5
        )

        assert answer['status'] == 'needs_lot_expiry'
        assert answer['line_id'] == line['id']
        after = _session_line(client, doc_auth_headers, doc_id, session_id)
        assert after['status'] == 'pending'
        assert after['received_quantity'] == 0

    def test_the_call_sent_again_with_lot_and_expiry_books_and_dates_the_line(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        line = _session_line(client, doc_auth_headers, doc_id, session_id)

        answer = _short_receive(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            line['id'],
            3,
            batch_number='LOT-S1',
            expiry_date=EXPIRY.isoformat(),
        )

        assert answer['status'] == 'short_receive_confirmed'
        assert answer['received_quantity'] == 3.0
        document_line = _line_of(client, doc_auth_headers, doc_id)
        assert document_line['batch_number'] == 'LOT-S1'
        assert document_line['expiry_date'] == EXPIRY.isoformat()

    def test_a_line_dated_by_an_earlier_scan_is_not_asked_again(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            expiry_date=EXPIRY.isoformat(),
        )
        line = _session_line(client, doc_auth_headers, doc_id, session_id)

        answer = _short_receive(
            client, doc_auth_headers, doc_id, session_id, line['id'], 5
        )

        assert answer['status'] == 'short_receive_confirmed'

    def test_a_line_that_arrived_with_nothing_needs_no_date(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        line = _session_line(client, doc_auth_headers, doc_id, session_id)

        answer = _short_receive(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            line['id'],
            0,
            discrepancy_code='SHORTAGE',
        )

        assert answer['status'] == 'short_receive_confirmed'

    def test_a_product_without_tracking_is_received_in_full_as_before(
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
        session_id = _start_session(client, doc_auth_headers, doc_id)
        line = _session_line(client, doc_auth_headers, doc_id, session_id)

        answer = _short_receive(
            client, doc_auth_headers, doc_id, session_id, line['id'], 5
        )

        assert answer['status'] == 'short_receive_confirmed'
        assert _line_of(client, doc_auth_headers, doc_id)['expiry_date'] is None


class TestTheReceivedStockCarriesLotAndExpiry:
    def test_completing_the_document_puts_both_on_the_stock_record(
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
            quantity=2,
        )
        session_id = _start_session(client, doc_auth_headers, doc_id)
        _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            batch_number='LOT-A1',
            expiry_date=EXPIRY.isoformat(),
        )

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == fefo_template.id)
        ).one()
        assert item.expiry_date == EXPIRY
        lot = db_session.get(StockLot, cast(uuid.UUID, item.lot_id))
        assert lot is not None
        assert lot.name == 'LOT-A1'
        assert lot.expiry_date == EXPIRY

    def test_a_date_without_a_lot_is_still_what_the_fefo_draw_reads(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        fefo_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The lot is optional on the sheet; the date is what makes it FEFO stock.

        A pack that shows a date and no lot number lands on the shelf with an
        expiry date and no batch. The draw used to read the batch alone, so
        that record sorted with the undated stock - the very case the scan's
        question exists to close. It is received between an earlier-dated
        record and a later-dated one, with an undated one beside them, and the
        draw has to take them in the order of their dates.
        """
        shelf = doc_target_location.id
        earlier = sow(
            db_session,
            async_engine_fixture,
            doc_org,
            fefo_template,
            shelf,
            '3',
            expiry_date=EXPIRY - timedelta(days=30),
        )
        later = sow(
            db_session,
            async_engine_fixture,
            doc_org,
            fefo_template,
            shelf,
            '3',
            expiry_date=EXPIRY + timedelta(days=30),
        )
        undated = sow(
            db_session, async_engine_fixture, doc_org, fefo_template, shelf, '3'
        )

        doc_id = _confirmed_receipt(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            fefo_template,
            quantity=2,
        )
        session_id = _start_session(client, doc_auth_headers, doc_id)
        _scan(
            client,
            doc_auth_headers,
            doc_id,
            session_id,
            fefo_template,
            expiry_date=EXPIRY.isoformat(),
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        received = db_session.scalars(
            select(Item).where(
                Item.template_id == fefo_template.id,
                Item.id.not_in([earlier.id, later.id, undated.id]),
            )
        ).one()
        assert received.expiry_date == EXPIRY
        assert received.lot_id is None

        async def _plan(session: AsyncSession) -> list[uuid.UUID]:
            plan = await plan_draw_async(
                session,
                doc_org.id,
                fefo_template.id,
                shelf,
                None,
                strategy='FEFO',
            )
            return [draw.record_id for draw in plan.draws]

        taken = run_in_async_session(async_engine_fixture, _plan)
        assert taken == [earlier.id, received.id, later.id, undated.id]
