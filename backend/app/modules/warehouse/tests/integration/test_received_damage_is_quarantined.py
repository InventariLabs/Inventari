"""A receipt line says how much of what arrived is held back.

The code on a short receipt line explains the gap: goods that never arrived,
refused at the door for damage or a quality decision, are backordered rather
than put into stock. Separately, the line may state how much of the quantity
it did receive is itself held back — damaged goods or goods awaiting a
quality decision. That quantity alone is kept out of available stock (a named
batch is quarantined, anything else goes to the quarantine shelf the profile
names), the rest lands as ordinary stock, and the order counts only what is
not held, so the difference is asked for again on a backorder.

This file pins those two readings and the tests that keep them apart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

pytestmark = pytest.mark.integration

CODES = ('DAMAGE', 'QUALITY_HOLD')
QUARANTINE_CODES = frozenset(CODES)


@pytest.fixture
def doc_quarantine_location(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Quarantine shelf'
    )


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
    quantity: int = 10,
    **line: Any,
) -> tuple[str, str]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                    **line,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    return str(doc['id']), str(doc['lines'][0]['id'])


def _complete(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    line_id: str,
    code: str | None,
    done: int = 7,
    held: int | None = None,
) -> Any:
    line: dict[str, Any] = {
        'line_id': line_id,
        'done_quantity': done,
        'discrepancy_reason': 'Supplier notice',
    }
    if code is not None:
        line['discrepancy_code'] = code
    if held is not None:
        line['held_quantity'] = held
    return client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'lines': [line]},
    )


def _name_quarantine_shelf(
    client: TestClient, headers: dict[str, str], shelf: StorageLocation
) -> None:
    resp = client.put(
        '/api/v1/warehouse/profile',
        headers=headers,
        json={'quarantine_location_id': str(shelf.id)},
    )
    assert resp.status_code == 200, resp.text


def _lots_in(client: TestClient, headers: dict[str, str], status: str) -> list[Any]:
    resp = client.get(f'/api/v1/stock-lots?status={status}', headers=headers)
    assert resp.status_code == 200, resp.text
    return list(resp.json()['items'])


def _line_of(client: TestClient, headers: dict[str, str], doc_id: str) -> Any:
    resp = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()['lines'][0]


def _stock_rows(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
) -> list[Any]:
    resp = client.get(
        '/api/v1/stock-quants',
        headers=headers,
        params={
            'product_template_id': str(template.id),
            'location_id': str(location.id),
        },
    )
    assert resp.status_code == 200, resp.text
    return list(resp.json()['items'])


def _stock_at(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
) -> Decimal:
    return sum(
        (
            Decimal(item['quantity'])
            for item in _stock_rows(client, headers, template, location)
        ),
        Decimal('0'),
    )


def _record_at(
    db_session: Session,
    organization_id: Any,
    template: ProductTemplate,
    location: StorageLocation,
) -> Item:
    """The stock record standing at the place — the one a document line names."""
    return db_session.scalars(
        select(Item).where(
            Item.organization_id == organization_id,
            Item.template_id == template.id,
            Item.storage_location_id == location.id,
            Item.is_deleted.is_(False),
        )
    ).one()


def _backorder_for(client: TestClient, headers: dict[str, str], doc_id: str) -> Any:
    docs = client.get('/api/v1/warehouse/documents', headers=headers).json()
    found = [d for d in docs['items'] if d.get('backorder_id') == doc_id]
    assert len(found) == 1, found
    # The list carries rows; the backorder's lines are on the document itself.
    return client.get(
        f'/api/v1/warehouse/documents/{found[0]["id"]}', headers=headers
    ).json()


class TestTheCodeOnAShortLine:
    """The gap is what the code explains; it does not hold the goods back."""

    @pytest.mark.parametrize('code', CODES)
    def test_the_received_goods_stay_available_and_the_gap_is_backordered(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        code: str,
    ) -> None:
        # No quarantine shelf is named: a receipt whose goods were refused at
        # the door has nothing to put in quarantine, so it must still complete.
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(client, doc_auth_headers, doc_id, line_id, code)

        assert resp.status_code == 200, resp.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('7')
        line = _line_of(client, doc_auth_headers, doc_id)
        assert Decimal(line['held_quantity']) == Decimal('0')
        assert (
            _backorder_for(client, doc_auth_headers, doc_id)['lines'][0][
                'expected_quantity'
            ]
            == '3.000'
        )

    def test_the_quantity_held_back_is_quarantined_and_only_that_quantity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        # Seven arrived, three of them checked and found damaged.
        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, 'DAMAGE', done=7, held=3
        )

        assert resp.status_code == 200, resp.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('4')
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('3')
        line = _line_of(client, doc_auth_headers, doc_id)
        assert Decimal(line['held_quantity']) == Decimal('3')
        assert line['executed_location_id'] == str(doc_target_location.id)
        # The order got four usable pieces; the other six are asked for again.
        assert (
            _backorder_for(client, doc_auth_headers, doc_id)['lines'][0][
                'expected_quantity'
            ]
            == '6.000'
        )

    def test_the_audit_log_names_the_held_quantity_and_its_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, 'DAMAGE', done=7, held=3
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        holds = [
            entry.snapshot or {}
            for entry in db_session.scalars(
                select(AuditLog).where(AuditLog.target_id == UUID(doc_id))
            ).all()
            if (entry.snapshot or {}).get('held_quantity')
        ]
        assert len(holds) == 1
        assert Decimal(holds[0]['held_quantity']) == Decimal('3')
        assert holds[0]['discrepancy_code'] == 'DAMAGE'
        assert holds[0]['discrepancy_reason'] == 'Supplier notice'

    def test_a_receipt_that_holds_nothing_writes_no_hold_row(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(client, doc_auth_headers, doc_id, line_id, None, done=10)
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        assert not [
            entry
            for entry in db_session.scalars(
                select(AuditLog).where(AuditLog.target_id == UUID(doc_id))
            ).all()
            if (entry.snapshot or {}).get('held_quantity')
        ]

    @pytest.mark.parametrize('code', CODES)
    def test_a_delivery_held_back_in_full_goes_to_the_quarantine_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        code: str,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, code, done=10, held=10
        )

        assert resp.status_code == 200, resp.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('0')
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('10')
        assert _line_of(client, doc_auth_headers, doc_id)[
            'executed_location_id'
        ] == str(doc_quarantine_location.id)
        assert (
            _backorder_for(client, doc_auth_headers, doc_id)['lines'][0][
                'expected_quantity'
            ]
            == '10.000'
        )

    @pytest.mark.parametrize('code', ['SHORTAGE', 'COUNT_VARIANCE', 'OTHER'])
    def test_the_other_codes_land_on_the_ordinary_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        code: str,
    ) -> None:
        doc_id, line_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            batch_number='B-79',
        )

        resp = _complete(client, doc_auth_headers, doc_id, line_id, code)

        assert resp.status_code == 200, resp.text
        assert _lots_in(client, doc_auth_headers, 'quarantined') == []
        assert _line_of(client, doc_auth_headers, doc_id)[
            'executed_location_id'
        ] == str(doc_target_location.id)


class TestTheWholeDeliveryHeldBackOnTheFloor:
    """The floor can record a delivery of which nothing is usable.

    The short-receive dialog asks for the counted total and the part of it
    held back; the two may be the same number. Completion must keep both the
    held quantity and the code that says why — the line is not short, and the
    old rule that cleared a code on a full line would leave the goods on the
    shelf they were never fit for.
    """

    def test_the_floor_records_a_full_delivery_held_back_in_full(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        doc_id, _line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()['id']
        wms_line_id = started.json()['lines'][0]['id']

        counted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': wms_line_id,
                'received_quantity': '10',
                'held_quantity': '10',
                'discrepancy_code': 'DAMAGE',
                'discrepancy_reason': 'The whole pallet was crushed',
            },
        )

        assert counted.status_code == 200, counted.text
        assert counted.json()['session_complete'] is True

        # The summary's close is a completion with no execution body, which is
        # exactly the path that used to clear a code from a line at its figure.
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={},
        )

        assert completed.status_code == 200, completed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('0')
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('10')
        line = _line_of(client, doc_auth_headers, doc_id)
        assert Decimal(line['held_quantity']) == Decimal('10')
        assert line['discrepancy_code'] == 'DAMAGE'


class TestAnUnknownCodeOnTheFloor:
    def test_a_short_receive_with_an_unknown_code_is_refused_and_the_document_still_reads(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, _line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/short-receive',
            headers=doc_auth_headers,
            json={
                'line_id': started.json()['lines'][0]['id'],
                'received_quantity': '7',
                'discrepancy_code': 'DAMAGED',
            },
        )

        assert resp.status_code == 422, resp.text
        assert "'DAMAGE'" in resp.text
        assert _line_of(client, doc_auth_headers, doc_id)['discrepancy_code'] is None


class TestWhatTheHeldQuantityMustAnswer:
    def test_a_held_quantity_above_what_arrived_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, 'DAMAGE', done=7, held=8
        )

        assert resp.status_code == 400, resp.text
        # Nothing was booked: the document is still waiting to be received.
        got = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert got.json()['status'] == 'CONFIRMED'

    def test_a_held_quantity_under_another_code_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, 'SHORTAGE', done=7, held=3
        )

        assert resp.status_code == 400, resp.text
        got = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert got.json()['status'] == 'CONFIRMED'

    def test_a_held_quantity_without_a_code_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, None, done=10, held=3
        )

        assert resp.status_code == 400, resp.text
        got = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert got.json()['status'] == 'CONFIRMED'

    def test_held_goods_with_nowhere_to_quarantine_are_refused_in_the_readers_language(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, line_id = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )

        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={
                'lines': [
                    {
                        'line_id': line_id,
                        'done_quantity': 7,
                        'held_quantity': 3,
                        'discrepancy_code': 'DAMAGE',
                        'discrepancy_reason': 'Crushed boxes',
                    }
                ]
            },
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['lang'] == 'pl'
        assert 'kwarantann' in detail['message']
        got = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert got.json()['status'] == 'CONFIRMED'


class TestTheBatchThatCarriesHeldGoods:
    @pytest.mark.parametrize('code', CODES)
    def test_the_batch_is_quarantined_and_the_good_part_stays_on_its_lot(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        code: str,
    ) -> None:
        doc_id, line_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            batch_number='B-77',
        )

        resp = _complete(
            client, doc_auth_headers, doc_id, line_id, code, done=7, held=3
        )

        assert resp.status_code == 200, resp.text
        held = _lots_in(client, doc_auth_headers, 'quarantined')
        assert [lot['name'] for lot in held] == ['B-77']
        assert held[0]['on_hand'] == '7.000'
        # The goods stay where the receipt put them: held back, not moved.
        assert _line_of(client, doc_auth_headers, doc_id)[
            'executed_location_id'
        ] == str(doc_target_location.id)
        # Four usable pieces reached the order; six are asked for again.
        assert (
            _backorder_for(client, doc_auth_headers, doc_id)['lines'][0][
                'expected_quantity'
            ]
            == '6.000'
        )


def _receive_held(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    quarantine: StorageLocation,
    template: ProductTemplate,
) -> str:
    """A receipt of ten with seven delivered and three of those held back."""
    _name_quarantine_shelf(client, headers, quarantine)
    doc_id, line_id = _receipt(client, headers, partner, target, template)
    resp = _complete(client, headers, doc_id, line_id, 'DAMAGE', done=7, held=3)
    assert resp.status_code == 200, resp.text
    return doc_id


class TestHeldGoodsAreOutOfEveryDraw:
    """The quarantine shelf is a destination; the hold must travel with it.

    Putting the goods on a shelf of their own says where they are, not that
    they may not be taken. The receipt reserves the batchless held quantity,
    so the stock view counts it as reserved rather than available, picking
    and dispatch refuse it, and only the transfer off the shelf releases it.
    """

    def test_the_held_quantity_is_reserved_and_not_available(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )

        held_rows = _stock_rows(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        )
        assert len(held_rows) == 1
        held = held_rows[0]
        assert Decimal(held['quantity']) == Decimal('3')
        assert Decimal(held['reserved_quantity']) == Decimal('3')
        assert Decimal(held['available_quantity']) == Decimal('0')
        assert held['lot_id'] is None

        # The good part is ordinary stock: on the shelf and freely available.
        good_rows = _stock_rows(
            client, doc_auth_headers, doc_template, doc_target_location
        )
        assert sum(
            (Decimal(row['available_quantity']) for row in good_rows), Decimal('0')
        ) == Decimal('4')

    def test_an_ordinary_dispatch_from_the_quarantine_shelf_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )
        held = _record_at(db_session, doc_org.id, doc_template, doc_quarantine_location)

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(held.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        out_id = created.json()['id']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{out_id}/confirm', headers=doc_auth_headers
        )

        assert confirmed.status_code == 400, confirmed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('3')

    def test_a_transfer_off_the_quarantine_shelf_releases_the_hold(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )
        held = _record_at(db_session, doc_org.id, doc_template, doc_quarantine_location)

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(held.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == 201, created.text
        transfer_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == 200, confirmed.text

        completed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert completed.status_code == 200, completed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('0')
        released = _stock_rows(
            client, doc_auth_headers, doc_template, doc_source_location
        )
        assert Decimal(released[0]['quantity']) == Decimal('3')
        assert Decimal(released[0]['reserved_quantity']) == Decimal('0')
        assert Decimal(released[0]['available_quantity']) == Decimal('3')

    def test_a_scrap_of_held_goods_writes_them_off(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )
        held = _record_at(db_session, doc_org.id, doc_template, doc_quarantine_location)

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'source_location_id': str(doc_quarantine_location.id),
                'lines': [{'item_id': str(held.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == 201, created.text
        scrap_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{scrap_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == 200, confirmed.text

        completed = client.patch(
            f'/api/v1/warehouse/documents/{scrap_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert completed.status_code == 200, completed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('0')
        db_session.expire_all()
        scrapped = db_session.get(Item, held.id)
        assert scrapped is not None and scrapped.quantity == Decimal('0')


class TestWhoOwnsTheQuarantineHold:
    """A release drops the receipt's hold, and nobody else's.

    The goods on the quarantine shelf are fungible, but the promises on them
    are not: the receipt holds the quantity it put there against itself, and
    an ordinary confirmed dispatch holds what it reserved. Carrying the
    goods off the shelf is the release of the receipt's hold — not a licence
    to take the dispatch's.
    """

    def test_a_transfer_releases_the_receipt_hold_and_leaves_another_documents_hold(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        receipt_id = _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )
        # Three ordinary pieces arrive on the same quarantine shelf; the
        # shelf now holds the receipt's three and three free ones.
        free_doc, free_line = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_quarantine_location,
            doc_template,
            quantity=3,
        )
        assert (
            _complete(
                client, doc_auth_headers, free_doc, free_line, None, done=3
            ).status_code
            == 200
        )
        # The two deliveries share the record their grain names — one record
        # per product and shelf — so the shelf's stock is one row of six,
        # three of it held by the receipt.
        record = _record_at(
            db_session, doc_org.id, doc_template, doc_quarantine_location
        )

        # An ordinary dispatch takes the free three.
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        out_id = created.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{out_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == 200
        )

        # A transfer off the quarantine shelf releases the receipt's hold.
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == 201, created.text
        transfer_id = created.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == 200, confirmed.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == 200, completed.text

        # The three left on the shelf are the dispatch's, not free stock: the
        # receipt's rows are gone and the dispatch's are not.
        left = _stock_rows(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        )
        assert sum((Decimal(row['quantity']) for row in left), Decimal('0')) == 3
        assert (
            sum((Decimal(row['reserved_quantity']) for row in left), Decimal('0')) == 3
        )
        assert (
            sum((Decimal(row['available_quantity']) for row in left), Decimal('0')) == 0
        )
        db_session.expire_all()
        remaining = db_session.scalars(
            select(StockReservation).where(
                StockReservation.organization_id == doc_org.id,
                StockReservation.document_id.in_([UUID(receipt_id), UUID(out_id)]),
            )
        ).all()
        assert {str(row.document_id) for row in remaining} == {out_id}

        # And its reservation is still there to complete it.
        dispatched = client.patch(
            f'/api/v1/warehouse/documents/{out_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert dispatched.status_code == 200, dispatched.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('0')

    def test_a_transfer_from_a_shelf_without_held_goods_reserves_like_any_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        # The profile names the shelf, but nothing on it is held: an ordinary
        # receipt put the goods there.
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        doc_id, line_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_quarantine_location,
            doc_template,
            quantity=3,
        )
        assert (
            _complete(
                client, doc_auth_headers, doc_id, line_id, None, done=3
            ).status_code
            == 200
        )
        record = _record_at(
            db_session, doc_org.id, doc_template, doc_quarantine_location
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        out_id = created.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{out_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == 200
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == 201, created.text
        transfer_id = created.json()['id']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/confirm',
            headers=doc_auth_headers,
        )

        # The dispatch's reservation is not the receipt's hold: the transfer
        # may not confirm and then take stock another document is holding.
        assert confirmed.status_code == 400, confirmed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('3')

    def test_a_receipt_hold_stays_releasable_after_the_profile_changes(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        _receive_held(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_quarantine_location,
            doc_template,
        )
        cleared = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'quarantine_location_id': None},
        )
        assert cleared.status_code == 200, cleared.text
        held = _record_at(db_session, doc_org.id, doc_template, doc_quarantine_location)

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_quarantine_location.id),
                'target_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(held.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == 201, created.text
        transfer_id = created.json()['id']

        # The hold belongs to the receipt that placed the goods, not to the
        # profile field: a later edit must not strand it.
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirmed.status_code == 200, confirmed.text
        completed = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == 200, completed.text
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('0')
        released = _stock_rows(
            client, doc_auth_headers, doc_template, doc_source_location
        )
        assert Decimal(released[0]['available_quantity']) == Decimal('3')


class TestTheQuarantineShelfInTheProfile:
    def test_the_profile_keeps_and_clears_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_quarantine_location: StorageLocation,
    ) -> None:
        _name_quarantine_shelf(client, doc_auth_headers, doc_quarantine_location)
        got = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        assert got.json()['quarantine_location_id'] == str(doc_quarantine_location.id)

        cleared = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'quarantine_location_id': None},
        )

        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['quarantine_location_id'] is None

    def test_a_shelf_of_another_organization_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
    ) -> None:
        other_org = h.create_org('Other Org', ['core', 'locations'])
        other_user = h.create_user(other_org, email='other@example.com')
        other_type = h.create_storage_type(
            'Warehouse', 'WAREHOUSE', organization_id=other_org.id
        )
        foreign = h.create_storage_location(
            other_org, other_type, other_user, name='Foreign shelf'
        )

        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'quarantine_location_id': str(foreign.id)},
        )

        assert resp.status_code in (400, 404), resp.text


class TestAHeldAnswerSurvivesAnApproval:
    """A posting parked on an approval keeps what the storekeeper said."""

    def test_the_approval_books_the_goods_held_back_to_quarantine(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_quarantine_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_approval_workflow: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.public_api import core_api

        async def _quiet(*_args: Any, **_kwargs: Any) -> bool:
            return True

        monkeypatch.setattr(core_api.email, 'send_async', _quiet)
        monkeypatch.setattr(core_api.notifications, 'publish_async', _quiet)
        profile = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={
                'quarantine_location_id': str(doc_quarantine_location.id),
                'approval_threshold': '1.00',
                'approval_required_for_types': [],
                'value_tracking_enabled': True,
            },
        )
        assert profile.status_code == 200, profile.text

        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '10.00',
                        'held_quantity': '3',
                        'discrepancy_code': 'DAMAGE',
                    }
                ],
            },
        )

        assert posted.status_code == 201, posted.text
        assert posted.json()['status'] == 'PENDING_APPROVAL'
        doc_id = posted.json()['id']
        # Nothing moved while the approval stands in the way, but the answer
        # is already on the line.
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('0')
        waiting = _line_of(client, doc_auth_headers, doc_id)
        assert Decimal(waiting['held_quantity']) == Decimal('3')
        assert waiting['discrepancy_code'] == 'DAMAGE'

        approved = client.post(
            f'/api/v1/approvals/documents/{doc_id}/approve', headers=doc_auth_headers
        )
        assert approved.status_code == 200, approved.text

        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_target_location
        ) == Decimal('7')
        assert _stock_at(
            client, doc_auth_headers, doc_template, doc_quarantine_location
        ) == Decimal('3')
        line = _line_of(client, doc_auth_headers, doc_id)
        assert Decimal(line['held_quantity']) == Decimal('3')
