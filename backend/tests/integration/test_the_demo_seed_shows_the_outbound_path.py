"""The outbound path the demo seed leaves standing, in four states.

The README and the gallery are photographed from this seed, so a visitor
reads the walk before they ever take part in it: a picking session that
walked two dispatches together, one of them packed into two boxes a slip
prints, one handed to a carrier under a tracking number, and one dispatch
still waiting to be picked. None of the first three is a row the seed can
write on its own — the session plans its lines from the shelves, a box is
bounded by what was picked, and a shipment rides the completion's own
transaction — so the seed walks those two dispatches through the
application's doors and this file pins what that walk leaves.

The states do not depend on where random placement put the stock: the
dispatches draw from the two shelves the receipts landed on, and the walk
runs after those receipts are posted. The numbers a screenshot may show
(document numbers, quantities) are read from the rows, not asserted.
"""

from __future__ import annotations

import io
import uuid

import pytest
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse._wms_line_utils import session_holds_document
from app.modules.warehouse.models import (
    Document,
    DocumentPackage,
    DocumentShipment,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
    WmsPickSessionDocument,
)
from app.modules.warehouse.packing_service import (
    package_code,
    packing_slip_pdf_async,
)
from app.modules.warehouse.shipment_service import tracking_url
from seed_demo_data import (
    DEMO_SHIPMENT_CARRIER,
    DEMO_SHIPMENT_TRACKING_NUMBER,
)
from tests.integration._demo_world import ids, seeded_organization
from tests.integration._shelf import run_in_async_session

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> uuid.UUID:
    """An organization seeded the way the demo reset seeds one."""
    payload = demo_world('org-60', seeded_organization(items=60))
    return ids(payload)[0]


def _dispatches(db: Session, org_id: uuid.UUID) -> list[Document]:
    """The organization's dispatches, in the order the register prints them."""
    return (
        db.query(Document)
        .filter(
            Document.organization_id == org_id,
            Document.type == 'OUT',
        )
        .order_by(Document.number)
        .all()
    )


def _walked_session(db: Session, org_id: uuid.UUID) -> WmsPickSession:
    """The one session the seed opened over more than one dispatch."""
    walked = [
        session
        for session in db.query(WmsPickSession)
        .filter(WmsPickSession.organization_id == org_id)
        .all()
        if db.query(WmsPickSessionDocument)
        .filter(WmsPickSessionDocument.session_id == session.id)
        .count()
        > 1
    ]
    assert len(walked) == 1, f'expected one walk, found {len(walked)}'
    return walked[0]


def _documents_of(db: Session, session: WmsPickSession) -> list[Document]:
    ids = [
        row.document_id
        for row in db.query(WmsPickSessionDocument)
        .filter(WmsPickSessionDocument.session_id == session.id)
        .all()
    ]
    return (
        db.query(Document).filter(Document.id.in_(ids)).order_by(Document.number).all()
    )


class TestOneSessionWalkedTwoDispatches:
    def test_the_session_closed_over_the_two_dispatches_it_opened_on(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        session = _walked_session(db_session, seeded)
        documents = _documents_of(db_session, session)

        assert session.status == 'completed', session.status
        assert session.completed_at is not None
        assert len(documents) == 2
        assert {doc.type for doc in documents} == {'OUT'}
        assert [doc.status for doc in documents] == [
            DocumentStatus.COMPLETED.value,
            DocumentStatus.COMPLETED.value,
        ]

    def test_every_line_was_taken_in_full(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        session = _walked_session(db_session, seeded)

        assert session.lines, 'the walk holds no lines'
        not_taken = [
            (
                line.product_name,
                line.status,
                line.picked_quantity,
                line.expected_quantity,
            )
            for line in session.lines
            if line.status != 'picked' or line.picked_quantity != line.expected_quantity
        ]
        assert not not_taken, f'lines the walk did not take in full: {not_taken}'

        for doc in _documents_of(db_session, session):
            short = [
                line.name
                for line in doc.lines
                if line.done_quantity != line.expected_quantity
            ]
            assert not short, f'{doc.number} completed with {short} not done'

    def test_the_lines_follow_the_walk_numbers_of_their_shelves(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """The order is the warehouse's, not the shelf codes'."""
        session = _walked_session(db_session, seeded)
        ordered = sorted(session.lines, key=lambda line: line.pick_order)

        shelves = [line.location_id for line in ordered]
        assert all(shelf is not None for shelf in shelves), 'a line with no shelf'
        assert len(set(shelves)) == 2, 'the walk did not leave one shelf for another'

        sequences = [
            db_session.get(StorageLocation, shelf).sequence for shelf in shelves
        ]
        assert all(sequence is not None for sequence in sequences), (
            'a shelf the walk took from carries no number'
        )
        assert sequences == sorted(sequences), (
            f'picked in {sequences}, which is not the order of the walk'
        )


class TestEveryDispatchDrawsFromAnExactShelf:
    def test_no_dispatch_names_a_place_with_shelves_under_it(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """A place with shelves under it is a zone, and a zone is drawn by plan.

        A dispatch from a zone splits each line over whichever shelves below
        it hold the product, in the product's removal order, so where random
        placement put the stock decided which shelves the walk visited: now
        two, now three. The demo's dispatches name a shelf, and the walk is
        the same on every seed.
        """
        for doc in _dispatches(db_session, seeded):
            under = (
                db_session.query(StorageLocation.id)
                .filter(StorageLocation.parent_id == doc.source_location_id)
                .count()
            )
            assert under == 0, f'{doc.number} draws from a place with {under} under it'


class TestOneDispatchWentOutInTwoBoxes:
    def _packed(self, db: Session, org_id: uuid.UUID) -> tuple[Document, list]:
        packages = (
            db.query(DocumentPackage)
            .filter(DocumentPackage.organization_id == org_id)
            .all()
        )
        assert len(packages) == 2, f'expected two boxes, found {len(packages)}'
        assert len({package.document_id for package in packages}) == 1, (
            'the boxes do not belong to one dispatch'
        )
        assert sorted(package.number for package in packages) == [1, 2]
        doc = db.get(Document, packages[0].document_id)
        assert doc is not None
        assert doc.status == DocumentStatus.COMPLETED.value
        return doc, packages

    def test_the_boxes_hold_what_the_walk_picked(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        doc, packages = self._packed(db_session, seeded)

        contents = [line for package in packages for line in package.lines]
        assert len(contents) == 2, 'a box holds no goods'
        packed = sum(line.quantity for line in contents)
        picked = sum(line.done_quantity for line in doc.lines)
        assert packed == picked, f'boxes hold {packed}, the dispatch picked {picked}'

    def test_the_slip_prints_both_boxes(
        self,
        db_session: Session,
        seeded: uuid.UUID,
        async_engine_fixture,
    ) -> None:
        doc, packages = self._packed(db_session, seeded)
        codes = [package_code(doc.number, package.number) for package in packages]
        # The async half opens its own connection; nothing may be pending here.
        db_session.commit()

        def _slip(adb):
            return packing_slip_pdf_async(adb, seeded, doc.id, None, 'en')

        _name, pdf = run_in_async_session(async_engine_fixture, _slip)
        text = ''.join(
            page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf)).pages
        )

        assert codes, 'the slip has no box to name'
        for code in codes:
            assert code in text, f'{code} missing from the slip'


class TestOneDispatchWentOutUnderATrackingNumber:
    def test_the_packed_dispatch_went_out_under_a_carrier(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """The boxes left the building: a hand-over a reader can follow.

        The shipment rides the completion, so it stands on the packed
        dispatch alone — the dispatch that walked with it closed without
        one, and so did the one still waiting to be picked.
        """
        boxes = (
            db_session.query(DocumentPackage)
            .filter(DocumentPackage.organization_id == seeded)
            .all()
        )
        assert boxes, 'no boxes were packed'
        packed = db_session.get(Document, boxes[0].document_id)
        assert packed is not None

        shipments = (
            db_session.query(DocumentShipment)
            .filter(DocumentShipment.organization_id == seeded)
            .all()
        )
        assert len(shipments) == 1, f'expected one hand-over, found {len(shipments)}'
        shipped = shipments[0]
        assert shipped.document_id == packed.id, (
            'the hand-over does not belong to the packed dispatch'
        )
        assert shipped.carrier == DEMO_SHIPMENT_CARRIER
        assert shipped.tracking_number == DEMO_SHIPMENT_TRACKING_NUMBER
        assert shipped.shipped_by is not None, 'no one is recorded as handing it over'
        assert packed.status == DocumentStatus.COMPLETED.value

        url = tracking_url(shipped.carrier, shipped.tracking_number)
        assert url and DEMO_SHIPMENT_TRACKING_NUMBER in url, (
            f'the tracking number leads nowhere: {url}'
        )


class TestTwoDispatchesStillWaitToBePicked:
    def _waiting(self, db: Session, org_id: uuid.UUID) -> list[Document]:
        waiting = [
            doc
            for doc in _dispatches(db, org_id)
            if doc.status == DocumentStatus.CONFIRMED.value
        ]
        # Two, so a visitor can try Pick N selected without writing a
        # delivery from scratch.
        assert len(waiting) == 2, f'expected two dispatches waiting, got {len(waiting)}'
        return waiting

    def test_a_confirmed_dispatch_has_never_been_in_a_session(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        for doc in self._waiting(db_session, seeded):
            held = (
                db_session.query(WmsPickSession)
                .filter(
                    session_holds_document(doc.id),
                    WmsPickSession.organization_id == seeded,
                )
                .count()
            )
            assert held == 0, f'{doc.number} is already held by a session'

            picked = (
                db_session.query(WmsPickLine)
                .filter(
                    WmsPickLine.document_line_id.in_([line.id for line in doc.lines])
                )
                .all()
            )
            assert not picked, f'{doc.number} already carries picked lines'

    def test_the_shelf_it_waits_at_holds_the_goods(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """A visitor who picks a waiting dispatch has to finish it as well."""
        for doc in self._waiting(db_session, seeded):
            for line in doc.lines:
                on_the_shelf = (
                    db_session.query(Item.id)
                    .filter(
                        Item.organization_id == seeded,
                        Item.template_id == line.product_template_id,
                        Item.storage_location_id == doc.source_location_id,
                        Item.is_deleted.is_(False),
                        Item.quantity >= line.expected_quantity,
                    )
                    .count()
                )
                assert on_the_shelf, (
                    f'{doc.number} draws {line.name} from a shelf that holds none'
                )


class TestEveryDispatchNamesItsCustomer:
    def test_each_dispatch_has_a_customer_and_no_suppliers_delivery_note(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """Duplicate and Create Return refuse a delivery that has no partner."""
        dispatches = _dispatches(db_session, seeded)
        assert dispatches
        for doc in dispatches:
            assert doc.partner_id is not None, f'{doc.number} has no customer'
            partner = db_session.get(Partner, doc.partner_id)
            assert partner is not None and partner.type == 'CUSTOMER', (
                f'{doc.number} goes to {partner and partner.type}, not a customer'
            )
            assert doc.partner_snapshot and doc.partner_snapshot['code'] == (
                partner.code
            )
            # A delivery note is the supplier's number on a receipt.
            assert doc.external_reference is None, doc.number

    def test_a_visitor_who_picks_it_can_complete_it(
        self,
        db_session: Session,
        seeded: uuid.UUID,
        async_engine_fixture,
    ) -> None:
        """Their lines name the stock they take, so the completion books it.

        A dispatch line that names a product alone is refused at completion
        ("lines must reference existing items"), and the seed wrote one
        that way: the visitor it waits for picked it and could not finish.
        Both waiting deliveries draw from one shelf, so they finish in turn.
        """
        waiting = [
            doc
            for doc in _dispatches(db_session, seeded)
            if doc.status == DocumentStatus.CONFIRMED.value
        ]
        assert len(waiting) >= 2, 'Pick N selected needs two waiting deliveries'
        doc_ids = [doc.id for doc in waiting]
        user_id = waiting[0].created_by
        db_session.commit()

        async def _complete(adb):
            from app.modules.warehouse._document_workflow_transitions import (
                complete_document,
            )
            from app.modules.warehouse.schemas import DocumentComplete

            for doc_id in doc_ids:
                await complete_document(
                    adb,
                    seeded,
                    doc_id,
                    user_id,
                    execution_data=DocumentComplete(complete_as_planned=True),
                )

        run_in_async_session(async_engine_fixture, _complete)

        db_session.expire_all()
        for doc_id in doc_ids:
            doc = db_session.get(Document, doc_id)
            assert doc is not None
            assert doc.status == DocumentStatus.COMPLETED.value, (
                doc.number,
                doc.status,
            )
            assert all(line.done_quantity == line.quantity for line in doc.lines)


class TestNothingUnfinishedReadsAsDone:
    def test_a_document_still_open_has_done_nothing_yet(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """Only a finished document carries done quantities.

        The dispatch waiting to be picked and the draft transfer were
        written with every line done, so the first opened as "fully
        executed and ready to close" beside a packing panel and a scan
        window that both said nothing had been picked.
        """
        open_documents = (
            db_session.query(Document)
            .filter(
                Document.organization_id == seeded,
                Document.status != DocumentStatus.COMPLETED.value,
            )
            .all()
        )
        assert {doc.status for doc in open_documents} >= {
            DocumentStatus.CONFIRMED.value
        }, 'the seed left no confirmed document to check'

        done = [
            (doc.number, line.name, line.done_quantity)
            for doc in open_documents
            for line in doc.lines
            if line.done_quantity
        ]
        assert not done, f'open documents with lines already done: {done}'


class TestTheShelvesAreNumberedForTheWalk:
    def test_every_location_carries_its_place_in_the_walk(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        locations = (
            db_session.query(StorageLocation)
            .filter(StorageLocation.organization_id == seeded)
            .all()
        )
        assert len(locations) >= 20, f'only {len(locations)} locations to number'

        unnumbered = [
            location.name for location in locations if location.sequence is None
        ]
        assert not unnumbered, f'locations with no walk number: {unnumbered}'

        numbers = [location.sequence for location in locations]
        assert len(set(numbers)) == len(numbers), 'two locations share a walk number'
