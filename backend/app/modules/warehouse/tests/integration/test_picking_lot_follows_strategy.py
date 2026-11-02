"""The batch a pick line plans, shows, checks and books is one batch.

Planning used to take the oldest record whatever the product's strategy
said, the row showed the batch only when the document line happened to name
one, a scan naming another batch warned nobody, and completion drew by the
strategy over every active batch — so the batch in the books could differ
from the batch that left the shelf.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from app.modules.warehouse.models import DocumentLine, WmsPickLine, WmsPickLineLot
from app.modules.warehouse.tests.integration._records import sow as _sow
from app.modules.warehouse.tests.integration.test_wms_picking import (
    _confirm_document,
)

_TODAY = datetime.now(UTC).date()


class _Floor:
    """An OUT document over one shelf holding two batches of the product."""

    def __init__(self) -> None:
        self.doc_id: str
        self.doc_ids: list[str]
        self.session_id: str
        self.start_line: dict[str, Any]
        self.start_lines: list[dict[str, Any]]
        self.first: StockLot
        self.second: StockLot
        self.barcode: str | None
        self.headers: dict[str, str]
        self.client: TestClient

    def scan(self, **body: Any) -> dict[str, Any]:
        response = self.client.post(
            f'/api/v1/warehouse/documents/{self.doc_id}/picking/{self.session_id}/scan',
            headers=self.headers,
            json={'barcode': self.barcode, 'quantity': 5, **body},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        return cast('dict[str, Any]', response.json())


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
    """Build the floor: *strategy* on the card, the batch dates, then a started session.

    The first batch is received first (the older record) and expires later;
    the second is received later and expires sooner — the pair on which FIFO
    and FEFO disagree.
    """

    def build(
        strategy: str | None, quantity: int = 5, lines: int = 1, documents: int = 1
    ) -> _Floor:
        template_id = doc_item.template_id or doc_template.id
        doc_template.removal_strategy = strategy
        first = StockLot(
            organization_id=doc_org.id,
            product_template_id=template_id,
            name='LOT-FIRST',
            expiry_date=_TODAY + timedelta(days=300),
        )
        second = StockLot(
            organization_id=doc_org.id,
            product_template_id=template_id,
            name='LOT-SECOND',
            expiry_date=_TODAY + timedelta(days=30),
        )
        db_session.add_all([first, second])
        db_session.flush()
        for lot in (first, second):
            _sow(
                db_session,
                async_engine_fixture,
                doc_org,
                doc_template,
                doc_source_location.id,
                '20',
                lot_id=lot.id,
            )
        doc_ids: list[str] = []
        for _ in range(documents):
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
                        for _ in range(lines)
                    ],
                },
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text
            doc_id = created.json()['id']
            _confirm_document(client, doc_auth_headers, doc_id)
            doc_ids.append(doc_id)
        if documents == 1:
            start = client.post(
                f'/api/v1/warehouse/documents/{doc_ids[0]}/picking/start',
                headers=doc_auth_headers,
            )
        else:
            start = client.post(
                '/api/v1/warehouse/picking/start',
                headers=doc_auth_headers,
                json={'document_ids': doc_ids},
            )
        assert start.status_code == status.HTTP_201_CREATED, start.text

        built = _Floor()
        built.doc_id = doc_ids[0]
        built.doc_ids = doc_ids
        built.session_id = start.json()['id']
        built.first, built.second = first, second
        built.barcode = doc_template.barcode
        built.headers = doc_auth_headers
        built.client = client
        built.start_line = start.json()['lines'][0]
        built.start_lines = start.json()['lines']
        return built

    return build


@pytest.mark.integration
class TestThePlannedBatchFollowsTheStrategy:
    def test_fefo_plans_the_batch_that_expires_first(
        self, floor: Callable[..., _Floor]
    ) -> None:
        built = floor('FEFO')

        assert built.start_line['lot_id'] == str(built.second.id)

    def test_fifo_plans_the_oldest_record(self, floor: Callable[..., _Floor]) -> None:
        built = floor('FIFO')

        assert built.start_line['lot_id'] == str(built.first.id)

    def test_fifo_plans_the_batch_the_document_itself_holds(
        self, floor: Callable[..., _Floor]
    ) -> None:
        # Confirming this dispatch reserved FIFO's first lot whole for this
        # very document. That hold is not someone else's, so the batch is
        # still the one the strategy reaches first.
        built = floor('FIFO', quantity=20)

        assert built.start_line['lot_id'] == str(built.first.id)


@pytest.mark.integration
class TestTheRowAndTheScanNameTheBatch:
    def test_the_row_names_the_planned_batch(
        self, floor: Callable[..., _Floor]
    ) -> None:
        built = floor('FEFO')

        assert built.start_line['lot_name'] == 'LOT-SECOND'

    def test_the_scan_answers_with_the_planned_batch(
        self, floor: Callable[..., _Floor]
    ) -> None:
        built = floor('FEFO')

        answer = built.scan()

        assert answer['status'] == 'picked'
        assert answer['lot_name'] == 'LOT-SECOND'
        assert answer['planned_lot_name'] is None

    def test_the_batch_code_of_the_plan_is_no_warning(
        self, floor: Callable[..., _Floor]
    ) -> None:
        built = floor('FEFO')

        answer = built.scan(lot_name='lot-second ')

        assert answer['status'] == 'picked'
        assert answer['planned_lot_name'] is None

    def test_another_batch_is_booked_as_picked_and_the_warning_names_the_plan(
        self,
        floor: Callable[..., _Floor],
        db_session: Session,
    ) -> None:
        built = floor('FEFO')

        answer = built.scan(lot_name='LOT-FIRST')

        assert answer['status'] == 'picked'
        assert answer['lot_name'] == 'LOT-FIRST'
        assert answer['planned_lot_name'] == 'LOT-SECOND'
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.lot_id == built.first.id

    def test_a_batch_the_product_does_not_have_is_refused(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO')

        answer = built.scan(lot_name='NO-SUCH-LOT')

        assert answer['status'] == 'wrong_lot'
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.picked_quantity == 0

    def test_a_refused_scan_keeps_the_batch_of_the_line(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # Six units from the other batch is over the line's five: the scan
        # is refused, and the batch it named must not reach the line.
        built = floor('FEFO')

        answer = built.scan(lot_name='LOT-FIRST', quantity=6)

        assert answer['status'] == 'over_quantity'
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.lot_id == built.second.id
        assert line.lot_name == 'LOT-SECOND'

    def test_another_batch_continues_a_line_that_is_all_accounted_for_by_batches(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO')
        built.scan(quantity=2)

        answer = built.scan(lot_name='LOT-FIRST', quantity=3)

        assert answer['status'] == 'picked'
        assert answer['picked_quantity'] == 5
        assert answer['lot_name'] == 'LOT-FIRST'
        # the plan is contradicted by the first batch only
        assert answer['planned_lot_name'] is None
        db_session.expire_all()
        taken = {
            row.lot_name: row.quantity
            for row in db_session.scalars(select(WmsPickLineLot)).all()
        }
        assert taken == {'LOT-SECOND': 2, 'LOT-FIRST': 3}

    def test_a_quantity_picked_without_a_batch_is_not_relabelled_by_a_later_label(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # 25 has no single batch, so the line starts with none and 10 are
        # picked unlabelled -- the strategy's batches, not LOT-FIRST. A label
        # on the next scan must not put the whole 15 on one batch.
        built = floor('FEFO', quantity=25)
        assert built.scan(quantity=10)['status'] == 'picked'

        answer = built.scan(lot_name='LOT-FIRST', quantity=5)

        assert answer['status'] == 'wrong_lot'
        assert answer['picked_quantity'] == 10
        assert answer['lot_name'] is None
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.picked_quantity == 10
        assert line.lot_id is None

    @pytest.mark.parametrize('named', ['LOT-FIRST', 'LOT-SECOND'])
    def test_a_named_batch_that_cannot_give_the_quantity_is_refused(
        self, floor: Callable[..., _Floor], db_session: Session, named: str
    ) -> None:
        # Each batch holds 20 and the line wants 25: naming either one means
        # the line is booked from it alone, which it cannot be.
        built = floor('FEFO', quantity=25)

        answer = built.scan(lot_name=named, quantity=25)

        assert answer['status'] == 'lot_too_small'
        assert answer['lot_name'] == named
        assert answer['picked_quantity'] == 0
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.picked_quantity == 0
        assert line.lot_id is None  # no single batch was planned for 25

    def test_a_continuation_the_batch_cannot_give_is_refused(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # Two units from SECOND are fine; the other 23 without a label are
        # still SECOND's, which holds 20 -- accepting them would book the
        # line from two batches while the screen says one.
        built = floor('FEFO', quantity=25)
        assert built.scan(lot_name='LOT-SECOND', quantity=2)['status'] == 'picked'

        answer = built.scan(quantity=23)

        assert answer['status'] == 'lot_too_small'
        assert answer['lot_name'] == 'LOT-SECOND'
        assert answer['picked_quantity'] == 2
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.picked_quantity == 2
        assert line.lot_id == built.second.id

    def test_the_stock_the_document_itself_holds_counts_as_available(
        self, floor: Callable[..., _Floor]
    ) -> None:
        # Confirming reserved LOT-FIRST's 20 for this very document under
        # FIFO: naming that batch for 20 is the pick the reservation is for.
        built = floor('FIFO', quantity=20)

        answer = built.scan(lot_name='LOT-FIRST', quantity=20)

        assert answer['status'] == 'picked'
        assert answer['lot_name'] == 'LOT-FIRST'


@pytest.mark.integration
class TestCompletionBooksThePickedBatch:
    def _complete(self, built: _Floor) -> None:
        done = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/complete',
            headers=built.headers,
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        completed = built.client.patch(
            f'/api/v1/warehouse/documents/{built.doc_id}/complete',
            headers=built.headers,
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

    def _left_by_batch(
        self, db_session: Session, built: _Floor
    ) -> dict[uuid.UUID, int]:
        from app.models.stock_move import StockMove

        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(StockMove.reference_id == uuid.UUID(built.doc_id))
        ).all()
        return {move.lot_id: int(move.quantity) for move in moves if move.lot_id}

    def test_the_booked_batch_is_the_planned_one_not_the_fifo_one(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # Plan and strategy agree here; the next test is the one where only
        # the pinned batch can make the books follow the shelf.
        built = floor('FEFO')
        built.scan()
        self._complete(built)

        assert self._left_by_batch(db_session, built) == {built.second.id: 5}

    def test_the_booked_batch_is_the_one_that_was_scanned(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO')
        built.scan(lot_name='LOT-FIRST')
        self._complete(built)

        assert self._left_by_batch(db_session, built) == {built.first.id: 5}

    def test_a_line_no_single_batch_can_give_plans_none_and_follows_the_strategy(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # The first batch in order holds 20; the line wants 25. No batch is
        # planned, so there is no picked batch to book -- the strategy serves
        # the line across both.
        built = floor('FEFO', quantity=25)
        assert built.start_line['lot_id'] is None
        built.scan(quantity=25)
        self._complete(built)

        assert self._left_by_batch(db_session, built) == {
            built.second.id: 20,
            built.first.id: 5,
        }

    def test_two_lines_do_not_share_a_batch_that_has_stock_for_one(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # Both batches hold 20 and each of the two lines wants 15. The first
        # line takes LOT-SECOND; it has nothing left for the second, which
        # plans no batch and is served by the strategy across both -- the
        # picking closes and the document completes, as it does without
        # batches in the plan.
        built = floor('FEFO', quantity=15, lines=2)
        planned = [ln['lot_id'] for ln in built.start_lines]
        assert planned.count(str(built.second.id)) == 1
        assert planned.count(None) == 1

        for _ in built.start_lines:
            built.scan(quantity=15)
        self._complete(built)

        # the second line's 15: 5 left in LOT-SECOND, 10 from LOT-FIRST
        assert self._left_by_batch(db_session, built)[built.first.id] == 10

    def test_a_dispatch_let_go_of_mid_session_books_the_batch_picked_for_it(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # One session over two dispatches. The first is picked from the
        # batch the strategy does not plan and completes while the session
        # goes on for the second: its books follow the shelf, not FEFO.
        built = floor('FEFO', documents=2)
        built.scan(lot_name='LOT-FIRST')

        completed = built.client.patch(
            f'/api/v1/warehouse/documents/{built.doc_ids[0]}/complete',
            headers=built.headers,
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        db_session.expire_all()
        from app.models.stock_move import StockMove

        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.reference_id == uuid.UUID(built.doc_ids[0])
            )
        ).all()
        assert {move.lot_id: int(move.quantity) for move in moves if move.lot_id} == {
            built.first.id: 5
        }

    def test_a_picked_batch_that_went_off_before_closing_blocks_the_closing(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # Two units came off LOT-SECOND; then the batch is quarantined. Closing
        # the line would leave the document naming no batch and let the strategy
        # book the two units from another one -- not the batch that left.
        built = floor('FEFO')
        built.scan(quantity=2)
        db_session.expire_all()
        built.second.status = 'quarantined'
        db_session.commit()

        short = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/short-pick',
            headers=built.headers,
            json={
                'line_id': built.start_line['id'],
                'picked_quantity': 2,
                'discrepancy_code': 'SHORTAGE',
            },
        )

        assert short.status_code == status.HTTP_400_BAD_REQUEST, short.text
        assert 'LOT-SECOND' in short.text
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(
                WmsPickLine.session_id == uuid.UUID(built.session_id)
            )
        ).one()
        assert line.status == 'pending'
        assert line.lot_id == built.second.id

    def test_a_batch_the_document_line_names_is_left_alone(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO')
        db_session.expire_all()
        line = db_session.scalars(
            select(DocumentLine).where(
                DocumentLine.document_id == uuid.UUID(built.doc_id)
            )
        ).one()
        line.batch_number = 'LOT-FIRST'
        db_session.commit()
        built.scan()
        self._complete(built)

        assert self._left_by_batch(db_session, built) == {built.first.id: 5}


@pytest.mark.integration
class TestALinePickedFromSeveralBatchesIsBookedFromEach:
    """25 where each batch holds 20: the document names both batches."""

    def _complete(self, built: _Floor) -> None:
        done = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/complete',
            headers=built.headers,
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        completed = built.client.patch(
            f'/api/v1/warehouse/documents/{built.doc_id}/complete',
            headers=built.headers,
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

    def _lines(self, db_session: Session, built: _Floor) -> list[DocumentLine]:
        db_session.expire_all()
        return list(
            db_session.scalars(
                select(DocumentLine)
                .where(DocumentLine.document_id == uuid.UUID(built.doc_id))
                .order_by(DocumentLine.line_number)
            ).all()
        )

    def _left_by_batch(
        self, db_session: Session, built: _Floor
    ) -> dict[uuid.UUID, int]:
        from app.models.stock_move import StockMove

        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(StockMove.reference_id == uuid.UUID(built.doc_id))
        ).all()
        return {move.lot_id: int(move.quantity) for move in moves if move.lot_id}

    def test_the_document_line_is_split_into_one_line_per_batch_picked(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # The strategy would take SECOND's 20 and FIRST's 5; the picker took
        # 10 of SECOND and 15 of FIRST. The books must say what left.
        built = floor('FEFO', quantity=25)
        assert built.scan(lot_name='LOT-SECOND', quantity=10)['status'] == 'picked'
        assert built.scan(lot_name='LOT-FIRST', quantity=15)['status'] == 'picked'
        self._complete(built)

        lines = self._lines(db_session, built)
        assert [
            (ln.line_number, ln.batch_number, int(ln.done_quantity)) for ln in lines
        ] == [(1, 'LOT-SECOND', 10), (2, 'LOT-FIRST', 15)]
        assert [int(ln.quantity) for ln in lines] == [10, 15]
        assert self._left_by_batch(db_session, built) == {
            built.second.id: 10,
            built.first.id: 15,
        }

    def test_the_lines_that_follow_the_split_one_are_renumbered(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO', quantity=15, lines=2)
        built.scan(lot_name='LOT-SECOND', quantity=10)
        built.scan(lot_name='LOT-FIRST', quantity=5)
        built.scan(lot_name='LOT-FIRST', quantity=10)
        built.scan(lot_name='LOT-SECOND', quantity=5)
        self._complete(built)

        lines = self._lines(db_session, built)
        assert [ln.line_number for ln in lines] == [1, 2, 3, 4]
        assert [(ln.batch_number, int(ln.done_quantity)) for ln in lines] == [
            ('LOT-SECOND', 10),
            ('LOT-FIRST', 5),
            ('LOT-FIRST', 10),
            ('LOT-SECOND', 5),
        ]

    def test_what_is_still_to_pick_stays_on_the_first_line(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        # 22 of 25 picked from two batches and the line closed short: the
        # missing 3 stay with the original line, which a backorder reads.
        built = floor('FEFO', quantity=25)
        built.scan(lot_name='LOT-SECOND', quantity=20)
        built.scan(lot_name='LOT-FIRST', quantity=2)
        short = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/short-pick',
            headers=built.headers,
            json={
                'line_id': built.start_line['id'],
                'picked_quantity': 22,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.status_code == status.HTTP_200_OK, short.text
        built.client.patch(
            f'/api/v1/warehouse/documents/{built.doc_id}/complete',
            headers=built.headers,
        )

        first, second = self._lines(db_session, built)
        assert (first.batch_number, int(first.quantity), int(first.done_quantity)) == (
            'LOT-SECOND',
            23,
            20,
        )
        assert first.discrepancy_code == 'SHORTAGE'
        assert (
            second.batch_number,
            int(second.quantity),
            int(second.done_quantity),
        ) == (
            'LOT-FIRST',
            2,
            2,
        )
        assert second.discrepancy_code is None

    def test_a_count_below_the_scans_takes_the_difference_off_the_last_batch(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO', quantity=25)
        built.scan(lot_name='LOT-SECOND', quantity=20)
        built.scan(lot_name='LOT-FIRST', quantity=4)
        short = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/short-pick',
            headers=built.headers,
            json={
                'line_id': built.start_line['id'],
                'picked_quantity': 22,
                'replace_scans': True,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.status_code == status.HTTP_200_OK, short.text
        built.client.patch(
            f'/api/v1/warehouse/documents/{built.doc_id}/complete',
            headers=built.headers,
        )

        assert self._left_by_batch(db_session, built) == {
            built.second.id: 20,
            built.first.id: 2,
        }

    def test_undoing_a_line_forgets_the_batches_it_took(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO', quantity=25)
        built.scan(lot_name='LOT-SECOND', quantity=10)
        undone = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/undo',
            headers=built.headers,
            params={'line_id': built.start_line['id']},
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text

        db_session.expire_all()
        assert db_session.scalars(select(WmsPickLineLot)).all() == []

    def test_a_batch_that_cannot_give_its_share_blocks_the_closing(
        self, floor: Callable[..., _Floor], db_session: Session
    ) -> None:
        built = floor('FEFO', quantity=25)
        built.scan(lot_name='LOT-SECOND', quantity=10)
        built.scan(lot_name='LOT-FIRST', quantity=10)
        db_session.expire_all()
        built.first.status = 'quarantined'
        db_session.commit()

        done = built.client.post(
            f'/api/v1/warehouse/documents/{built.doc_id}/picking/{built.session_id}/short-pick',
            headers=built.headers,
            json={
                'line_id': built.start_line['id'],
                'picked_quantity': 20,
                'discrepancy_code': 'SHORTAGE',
            },
        )

        assert done.status_code == status.HTTP_400_BAD_REQUEST, done.text
        assert 'LOT-FIRST' in done.text
