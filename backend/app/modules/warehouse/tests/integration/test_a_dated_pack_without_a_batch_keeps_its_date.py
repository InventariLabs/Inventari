"""Stock with a date and no batch tells the picker, the document and the ledger its date.

A pack received with a date but no lot number is a record carrying the date
itself, and FEFO draws by it. The picking row used to show the batch only,
so two dated packs of one product on a shelf left the picker guessing which
one the draw chose, and the completed dispatch line and the movement it
wrote said nothing of the date that left.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import DocumentLine
from app.modules.warehouse.tests.integration._records import sow as _sow
from app.modules.warehouse.tests.integration.test_wms_picking import (
    _confirm_document,
)

_TODAY = datetime.now(UTC).date()
_SOON = _TODAY + timedelta(days=10)
_LATER = _TODAY + timedelta(days=30)


class _Floor:
    def __init__(self) -> None:
        self.doc_id: str
        self.session_id: str
        self.start_line: dict[str, Any]
        self.headers: dict[str, str]
        self.client: TestClient
        self.db: Session


@pytest.fixture
def floor(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    doc_template: ProductTemplate,
    doc_org: Organization,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> Callable[..., _Floor]:
    """An OUT of *quantity* over a shelf holding the records *stock* describes.

    Each entry of *stock* is ``(quantity, date, batch)``; the later the entry,
    the later the record was received. FEFO is the product's strategy.
    """

    def build(stock: list[tuple[int, date | None, bool]], quantity: int) -> _Floor:
        template_id = doc_item.template_id or doc_template.id
        doc_template.removal_strategy = 'FEFO'
        for amount, day, in_a_batch in stock:
            lot_id: uuid.UUID | None = None
            if in_a_batch:
                lot = StockLot(
                    organization_id=doc_org.id,
                    product_template_id=template_id,
                    name=f'LOT-{amount}-{day}',
                    expiry_date=day,
                )
                db_session.add(lot)
                db_session.flush()
                lot_id = lot.id
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                doc_template,
                doc_source_location.id,
                str(amount),
                lot_id=lot_id,
                expiry_date=None if in_a_batch else day,
            )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': quantity,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        _confirm_document(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text

        built = _Floor()
        built.doc_id = doc_id
        built.session_id = start.json()['id']
        built.start_line = start.json()['lines'][0]
        built.headers = doc_auth_headers
        built.client = client
        built.db = db_session
        return built

    return build


def _complete(built: _Floor, barcode: str | None, quantity: int) -> None:
    scanned = built.client.post(
        f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/scan',
        headers=built.headers,
        json={'barcode': barcode, 'quantity': quantity},
    )
    assert scanned.status_code == status.HTTP_200_OK, scanned.text
    done = built.client.post(
        f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/complete',
        headers=built.headers,
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    completed = built.client.patch(
        f'/api/v1/warehouse/documents/{built.doc_id}/complete', headers=built.headers
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text


def _lines(built: _Floor) -> list[DocumentLine]:
    built.db.expire_all()
    return list(
        built.db.scalars(
            select(DocumentLine)
            .where(DocumentLine.document_id == uuid.UUID(built.doc_id))
            .order_by(DocumentLine.line_number)
        ).all()
    )


def _moves(built: _Floor) -> list[StockMove]:
    built.db.expire_all()
    return list(
        built.db.scalars(
            select(StockMove).where(StockMove.reference_id == uuid.UUID(built.doc_id))
        ).all()
    )


@pytest.mark.integration
class TestThePickingRowShowsTheDateToTake:
    def test_a_dated_pack_without_a_batch_shows_its_own_date(
        self, floor: Callable[..., _Floor]
    ) -> None:
        # Received first, expires last: FEFO still reaches the later pack
        # second, and the row says which date it reaches first.
        built = floor([(5, _LATER, False), (5, _SOON, False)], quantity=4)

        assert built.start_line['lot_id'] is None
        assert built.start_line['expiry_date'] == _SOON.isoformat()

    def test_a_batch_shows_the_date_of_the_batch(
        self, floor: Callable[..., _Floor]
    ) -> None:
        built = floor([(5, _LATER, True), (5, _SOON, True)], quantity=4)

        assert built.start_line['lot_name'] == f'LOT-5-{_SOON}'
        assert built.start_line['expiry_date'] == _SOON.isoformat()

    def test_undated_stock_shows_no_date(self, floor: Callable[..., _Floor]) -> None:
        built = floor([(5, None, False)], quantity=4)

        assert built.start_line['expiry_date'] is None


@pytest.mark.integration
class TestTheCompletedDispatchRecordsTheDateThatLeft:
    def test_the_line_and_the_move_carry_the_date_of_the_record_taken(
        self, floor: Callable[..., _Floor], doc_template: ProductTemplate
    ) -> None:
        built = floor([(5, _LATER, False), (5, _SOON, False)], quantity=4)
        _complete(built, doc_template.barcode, 4)

        assert [ln.expiry_date for ln in _lines(built)] == [_SOON]
        assert [(m.expiry_date, int(m.quantity)) for m in _moves(built)] == [(_SOON, 4)]

    def test_a_line_that_crossed_dates_is_split_per_date(
        self, floor: Callable[..., _Floor], doc_template: ProductTemplate
    ) -> None:
        built = floor([(5, _LATER, False), (5, _SOON, False)], quantity=8)
        _complete(built, doc_template.barcode, 8)

        assert [(ln.expiry_date, int(ln.done_quantity)) for ln in _lines(built)] == [
            (_SOON, 5),
            (_LATER, 3),
        ]
        assert sorted((m.expiry_date, int(m.quantity)) for m in _moves(built)) == [
            (_SOON, 5),
            (_LATER, 3),
        ]

    def test_a_batch_line_carries_the_date_of_the_batch_that_left(
        self, floor: Callable[..., _Floor], doc_template: ProductTemplate
    ) -> None:
        built = floor([(5, _LATER, True), (5, _SOON, True)], quantity=4)
        _complete(built, doc_template.barcode, 4)

        assert [m.expiry_date for m in _moves(built)] == [_SOON]
        assert [(ln.batch_number, ln.expiry_date) for ln in _lines(built)] == [
            (f'LOT-5-{_SOON}', _SOON)
        ]

    def test_undated_stock_leaves_the_line_and_the_move_undated(
        self, floor: Callable[..., _Floor], doc_template: ProductTemplate
    ) -> None:
        built = floor([(5, None, False)], quantity=4)
        _complete(built, doc_template.barcode, 4)

        assert [ln.expiry_date for ln in _lines(built)] == [None]
        assert [m.expiry_date for m in _moves(built)] == [None]


@pytest.mark.integration
class TestADateSplitKeepsTheShelfOfAZoneDispatch:
    def test_every_date_line_says_which_shelf_it_left(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """A correction of a sibling lands where its goods left, not on the zone."""
        shelf = StorageLocation(
            organization_id=doc_org.id,
            name='Dated Bin',
            parent_id=doc_source_location.id,
            storage_type_id=doc_source_location.storage_type_id,
            created_by=doc_user.id,
        )
        db_session.add(shelf)
        db_session.flush()
        doc_template.removal_strategy = 'FEFO'
        db_session.commit()
        first = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf.id,
            '5',
            expiry_date=_LATER,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf.id,
            '5',
            expiry_date=_SOON,
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(first.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 8,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        for step, body in (
            ('confirm', None),
            ('complete', {'complete_as_planned': True}),
        ):
            done = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/{step}',
                headers=doc_auth_headers,
                json=body,
            )
            assert done.status_code == status.HTTP_200_OK, done.text

        db_session.expire_all()
        lines = db_session.scalars(
            select(DocumentLine)
            .where(DocumentLine.document_id == uuid.UUID(doc_id))
            .order_by(DocumentLine.line_number)
        ).all()
        assert [(ln.expiry_date, ln.executed_location_id) for ln in lines] == [
            (_SOON, shelf.id),
            (_LATER, shelf.id),
        ]


def _dispatch_two_dated_packs(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    engine: AsyncEngine,
    org: Organization,
    partner: Partner,
    template: ProductTemplate,
    source: StorageLocation,
    target: StorageLocation,
    *,
    quantity: int,
    uom_id: uuid.UUID | None = None,
) -> tuple[str, Item, Item]:
    """Two 5-unit dated packs, the later received first, dispatched in one line.

    Answers the document and the two records, the nearer date first.
    """
    template.removal_strategy = 'FEFO'
    later = _sow(db, engine, org, template, source.id, '5', expiry_date=_LATER)
    sooner = _sow(db, engine, org, template, source.id, '5', expiry_date=_SOON)
    line: dict[str, Any] = {
        'item_id': str(later.id),
        'product_template_id': str(template.id),
        'expected_quantity': quantity,
    }
    if uom_id is not None:
        line['uom_id'] = str(uom_id)
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'target_location_id': str(target.id),
            'lines': [line],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    for step, body in (('confirm', None), ('complete', {'complete_as_planned': True})):
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/{step}', headers=headers, json=body
        )
        assert done.status_code == status.HTTP_200_OK, done.text
    db.expire_all()
    return doc_id, sooner, later


def _document_lines(db: Session, doc_id: str) -> list[DocumentLine]:
    return list(
        db.scalars(
            select(DocumentLine)
            .where(DocumentLine.document_id == uuid.UUID(doc_id))
            .order_by(DocumentLine.line_number)
        ).all()
    )


@pytest.mark.integration
class TestADateSplitStandsForTheRecordsItTook:
    def test_a_line_in_the_suppliers_unit_is_split_in_that_unit(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template_with_uom: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """Eight thousand grams off two kilogram packs: 5000 g and 3000 g."""
        gram = ModuleTestHelper(db_session).get_uom('g')
        doc_id, _, _ = _dispatch_two_dated_packs(
            client,
            doc_auth_headers,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_partner,
            doc_template_with_uom,
            doc_source_location,
            doc_target_location,
            quantity=8000,
            uom_id=gram.id,
        )

        lines = _document_lines(db_session, doc_id)
        assert [(ln.expiry_date, int(ln.done_quantity)) for ln in lines] == [
            (_SOON, 5000),
            (_LATER, 3000),
        ]
        assert all(ln.uom_id == gram.id for ln in lines)

    def test_every_date_line_is_valued_by_what_it_took(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """The outflow is attributed to each sibling, so a correction finds it."""
        doc_id, _, _ = _dispatch_two_dated_packs(
            client,
            doc_auth_headers,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_partner,
            doc_template,
            doc_source_location,
            doc_target_location,
            quantity=8,
        )

        lines = _document_lines(db_session, doc_id)
        out = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.direction == 'OUT',
            )
        ).all()
        assert sorted(
            (str(layer.document_line_id), int(layer.quantity)) for layer in out
        ) == sorted([(str(lines[0].id), 5), (str(lines[1].id), 3)])

    def test_a_correction_of_a_date_line_lands_on_the_record_of_that_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        doc_id, sooner, later = _dispatch_two_dated_packs(
            client,
            doc_auth_headers,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_partner,
            doc_template,
            doc_source_location,
            doc_target_location,
            quantity=8,
        )
        lines = _document_lines(db_session, doc_id)
        assert [ln.item_id for ln in lines] == [sooner.id, later.id]

        asked = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 2, 'quantity_delta': '-1'}],
            },
        )
        assert asked.status_code == status.HTTP_201_CREATED, asked.text
        correction = asked.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{correction}/confirm',
            headers=doc_auth_headers,
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{correction}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        db_session.expire_all()
        sooner_after = db_session.get(Item, sooner.id)
        later_after = db_session.get(Item, later.id)
        assert sooner_after is not None
        assert later_after is not None
        assert sooner_after.quantity == 0
        assert later_after.quantity == 3

    def test_a_draw_across_a_batchless_pack_and_a_batch_keeps_both(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """A line naming the dated pack, drawn on into a batch: one line each."""
        doc_template.removal_strategy = 'FEFO'
        lot = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='MIXED-BATCH',
            expiry_date=_LATER,
        )
        db_session.add(lot)
        db_session.flush()
        batched = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '5',
            lot_id=lot.id,
        )
        pack = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '5',
            expiry_date=_SOON,
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(pack.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 8,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        for step, body in (
            ('confirm', None),
            ('complete', {'complete_as_planned': True}),
        ):
            done = client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/{step}',
                headers=doc_auth_headers,
                json=body,
            )
            assert done.status_code == status.HTTP_200_OK, done.text
        db_session.expire_all()

        assert [
            (ln.batch_number, ln.expiry_date, int(ln.done_quantity))
            for ln in _document_lines(db_session, doc_id)
        ] == [(None, _SOON, 5), ('MIXED-BATCH', _LATER, 3)]

        # The batched part stands for the batch's own record, so a correction
        # of it gives the kilogram back to the batch, not to the dated pack.
        asked = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 2, 'quantity_delta': '-1'}],
            },
        )
        assert asked.status_code == status.HTTP_201_CREATED, asked.text
        correction = asked.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{correction}/confirm',
            headers=doc_auth_headers,
        )
        returned = client.patch(
            f'/api/v1/warehouse/documents/{correction}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert returned.status_code == status.HTTP_200_OK, returned.text
        db_session.expire_all()
        pack_after = db_session.get(Item, pack.id)
        batched_after = db_session.get(Item, batched.id)
        assert pack_after is not None
        assert batched_after is not None
        assert pack_after.quantity == 0
        assert batched_after.quantity == 3


@pytest.mark.integration
class TestAScanThatNamesAnotherBatchMovesTheDate:
    def test_the_row_answers_with_the_date_of_the_batch_scanned(
        self, floor: Callable[..., _Floor], doc_template: ProductTemplate
    ) -> None:
        built = floor([(5, _LATER, True), (5, _SOON, True)], quantity=4)

        scanned = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/scan',
            headers=built.headers,
            json={
                'barcode': doc_template.barcode,
                'quantity': 4,
                'lot_name': f'LOT-5-{_LATER}',
            },
        )

        assert scanned.status_code == status.HTTP_200_OK, scanned.text
        assert scanned.json()['expiry_date'] == _LATER.isoformat()
