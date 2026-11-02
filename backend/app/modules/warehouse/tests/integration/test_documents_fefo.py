"""
Integration tests for the FEFO/FIFO removal strategy in document execution.

The dispatch/scrap/transfer executors once called
``decrement_quant_async(lot_id=None)``, which only hit the lot-less quant.
When stock lived in lot-specific quants (real-world WMS data after
receiving via documents), dispatch silently failed or fell back to
whichever lot happened to match.

Now lines WITHOUT explicit ``batch_number``/``serial_number`` draw by
the removal strategy (FEFO by default, FIFO otherwise, honours
``ProductTemplate.removal_strategy``) — planned from the records, batch by
batch. Lines WITH explicit batch/serial honour that choice.

Tests:
- FEFO via dispatch (template FEFO, 3 lots different expiry → earliest consumed)
- Explicit batch_number via dispatch (chosen lot consumed, others untouched)
- Per-lot preservation via transfer (per-lot breakdown at destination)
- FEFO via scrap (template FEFO → earliest expiry consumed)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    shelf_quant,
    shelf_record,
    sow,
)
from tests.integration._holds import hold

# The batches these tests order have to be batches the warehouse would still
# release: stock past its date is held back now, and fixed calendar dates
# quietly walked into the past — every one of these was in the future when
# it was typed. Relative dates keep the subject FEFO ordering rather than
# how long ago the file was written.
_TODAY = datetime.now(UTC).date()


def _in_months(months: int) -> date:
    return _TODAY + timedelta(days=30 * months)


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    target_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None = None,
    serial_number: str | None = None,
) -> str:
    """Create + confirm + complete an OUT document. Returns doc id."""
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number
    if serial_number is not None:
        line['serial_number'] = serial_number

    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])

    confirm_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm_resp.status_code == status.HTTP_200_OK, confirm_resp.text

    complete_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete_resp.status_code == status.HTTP_200_OK, complete_resp.text
    return doc_id


def _create_int(
    client: TestClient,
    headers: dict[str, str],
    *,
    source_location_id: UUID,
    target_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
) -> str:
    """Create + confirm + complete an INT document. Returns doc id."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'INT',
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])

    confirm_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm_resp.status_code == status.HTTP_200_OK, confirm_resp.text

    complete_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete_resp.status_code == status.HTTP_200_OK, complete_resp.text
    return doc_id


def _create_scrap(
    client: TestClient,
    headers: dict[str, str],
    *,
    source_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
) -> str:
    """Create + confirm + complete a SCRAP document. Returns doc id."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(source_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])

    confirm_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm_resp.status_code == status.HTTP_200_OK, confirm_resp.text

    complete_resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete_resp.status_code == status.HTTP_200_OK, complete_resp.text
    return doc_id


def _make_lot(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    name: str,
    use_by_date: date | None,
) -> StockLot:
    lot = StockLot(
        organization_id=org_id,
        product_template_id=template_id,
        name=name,
        use_by_date=use_by_date,
    )
    db_session.add(lot)
    db_session.flush()
    db_session.refresh(lot)
    return lot


def _put_batch(
    db_session: Session,
    engine: AsyncEngine,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
    lot_id: UUID | None = None,
) -> ShelfRow:
    """One record of the batch on the shelf; returns the group it makes there."""
    template = db_session.get(ProductTemplate, template_id)
    assert template is not None
    sow(
        db_session,
        engine,
        org_id,
        template,
        location_id,
        quantity,
        lot_id=lot_id,
    )
    return shelf_quant(db_session, org_id, template_id, location_id, lot_id=lot_id)


def _quant_quantity(
    db_session: Session,
    org_id: UUID,
    lot_id: UUID,
    location_id: UUID,
) -> Decimal:
    """What the batch's records hold on the shelf; 0 once they are all gone."""
    group = db_session.scalars(
        select(ShelfRow).where(
            ShelfRow.organization_id == org_id,
            ShelfRow.lot_id == lot_id,
            ShelfRow.storage_location_id == location_id,
        )
    ).first()
    return group.quantity if group is not None else Decimal('0')


def _make_fefo_item(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """The record the document line names: one already standing on the shelf.

    The stock itself went in through ``sow`` (per batch); this picks up one
    of those records, so the line names a real one instead of a scalar row
    no batch on the shelf stands behind.
    """
    return shelf_record(db_session, org_id, template_id, location_id)


@pytest.mark.integration
class TestFefoDispatch:
    """OUT document without explicit batch/serial picks earliest-expiry lot first."""

    def test_dispatch_consumes_earliest_expiry_lot_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'FEFO Test {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)

        # Three lots with different use_by_date. B is earliest.
        lot_b = _make_lot(
            db_session,
            doc_org.id,
            template.id,
            'LOT-B',
            _in_months(3),
        )
        lot_c = _make_lot(
            db_session,
            doc_org.id,
            template.id,
            'LOT-C',
            _in_months(9),
        )
        lot_a = _make_lot(
            db_session,
            doc_org.id,
            template.id,
            'LOT-A',
            _in_months(12),
        )

        # 5 units per lot = 15 total. Item tracks scalar quantity = 15.
        for lot in (lot_a, lot_b, lot_c):
            _put_batch(
                db_session,
                async_engine_fixture,
                doc_org.id,
                template.id,
                doc_source_location.id,
                Decimal('5'),
                lot_id=lot.id,
            )

        item = _make_fefo_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('15'),
        )
        db_session.commit()

        # Dispatch 7 units WITHOUT batch_number. FEFO expects:
        #   LOT-B fully consumed (5), LOT-C partially (2), LOT-A untouched.
        _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=7,
        )

        assert _quant_quantity(
            db_session, doc_org.id, lot_b.id, doc_source_location.id
        ) == Decimal('0')
        assert _quant_quantity(
            db_session, doc_org.id, lot_c.id, doc_source_location.id
        ) == Decimal('3')
        assert _quant_quantity(
            db_session, doc_org.id, lot_a.id, doc_source_location.id
        ) == Decimal('5')

    def test_dispatch_with_explicit_lot_honors_choice(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Explicit Lot {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)

        lot_b = _make_lot(db_session, doc_org.id, template.id, 'LOT-B', _in_months(3))
        lot_a = _make_lot(db_session, doc_org.id, template.id, 'LOT-A', _in_months(12))
        for lot in (lot_a, lot_b):
            _put_batch(
                db_session,
                async_engine_fixture,
                doc_org.id,
                template.id,
                doc_source_location.id,
                Decimal('10'),
                lot_id=lot.id,
            )

        item = _make_fefo_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('20'),
        )
        db_session.commit()

        # Explicit batch_number='LOT-B' → operator chose that lot. Even
        # though FEFO would pick LOT-B first anyway (earlier expiry), the
        # contract is "explicit choice wins regardless of strategy".
        _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=5,
            batch_number='LOT-B',
        )

        assert _quant_quantity(
            db_session, doc_org.id, lot_b.id, doc_source_location.id
        ) == Decimal('5')
        assert _quant_quantity(
            db_session, doc_org.id, lot_a.id, doc_source_location.id
        ) == Decimal('10')


@pytest.mark.integration
class TestADispatchCountsTheRowsThatHoldABatch:
    """A dispatch without a batch plans its draw from the records and the rows."""

    def test_a_batch_its_reservation_rows_hold_is_passed_by(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        """The earliest batch is promised whole to another order.

        The row holding it is written by hand, naming the batch's grain:
        FEFO calls LOT-SOON first in line, the rows call it held. The
        dispatch takes LOT-LATER.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Promised {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)
        soon = _make_lot(db_session, doc_org.id, template.id, 'LOT-SOON', _in_months(2))
        later = _make_lot(
            db_session, doc_org.id, template.id, 'LOT-LATER', _in_months(8)
        )
        promised = _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=soon.id,
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=later.id,
        )
        hold(db_session, promised, Decimal('5'))
        item = _make_fefo_item(
            db_session, doc_org.id, template.id, doc_source_location.id, Decimal('10')
        )
        db_session.commit()

        _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=3,
        )

        assert _quant_quantity(
            db_session, doc_org.id, soon.id, doc_source_location.id
        ) == Decimal('5')
        assert _quant_quantity(
            db_session, doc_org.id, later.id, doc_source_location.id
        ) == Decimal('2')


@pytest.mark.integration
class TestFefoTransfer:
    """INT preserves lot identity across source → destination."""

    def test_transfer_preserves_lot_identity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Xfer Lot {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)

        lot_x = _make_lot(db_session, doc_org.id, template.id, 'LOT-X', _in_months(2))
        lot_y = _make_lot(db_session, doc_org.id, template.id, 'LOT-Y', _in_months(6))

        # 4 units of LOT-X, 6 units of LOT-Y at source, each in a record of
        # its own.
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('4'),
            lot_id=lot_x.id,
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('6'),
            lot_id=lot_y.id,
        )

        db_session.commit()

        # Transfer all 10 units, one line per record, the later batch first.
        # A line names no lot, and the record it names carries its own batch
        # — a line moving more than its record holds is refused — so each
        # batch lands at the target as itself, where FEFO would have handed
        # over LOT-X first: destination stock must remain per-lot (not
        # collapsed to lot-less), line by line.
        for lot, held in ((lot_y, Decimal('6')), (lot_x, Decimal('4'))):
            record = db_session.scalars(
                select(Item).where(
                    Item.organization_id == doc_org.id,
                    Item.template_id == template.id,
                    Item.storage_location_id == doc_source_location.id,
                    Item.lot_id == lot.id,
                    Item.is_deleted.is_(False),
                )
            ).one()
            _create_int(
                client,
                doc_auth_headers,
                source_location_id=doc_source_location.id,
                target_location_id=doc_target_location.id,
                item_id=record.id,
                template_id=template.id,
                quantity=int(record.quantity),
            )
            assert (
                _quant_quantity(db_session, doc_org.id, lot.id, doc_target_location.id)
                == held
            )

        # Destination groups must exist per-lot with same quantities.
        assert _quant_quantity(
            db_session, doc_org.id, lot_x.id, doc_target_location.id
        ) == Decimal('4')
        assert _quant_quantity(
            db_session, doc_org.id, lot_y.id, doc_target_location.id
        ) == Decimal('6')

        # Source groups drained (their records are gone).
        assert _quant_quantity(
            db_session, doc_org.id, lot_x.id, doc_source_location.id
        ) == Decimal('0')
        assert _quant_quantity(
            db_session, doc_org.id, lot_y.id, doc_source_location.id
        ) == Decimal('0')


@pytest.mark.integration
class TestFefoScrap:
    """SCRAP document without explicit batch/serial picks earliest-expiry lot first."""

    def test_scrap_uses_fefo(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Scrap FEFO {uuid4().hex[:6]}')
        template.removal_strategy = 'FEFO'
        db_session.commit()
        db_session.refresh(template)

        lot_old = _make_lot(
            db_session, doc_org.id, template.id, 'OLD-LOT', _in_months(1)
        )
        lot_mid = _make_lot(
            db_session, doc_org.id, template.id, 'MID-LOT', _in_months(5)
        )
        lot_new = _make_lot(
            db_session, doc_org.id, template.id, 'NEW-LOT', _in_months(12)
        )
        for lot in (lot_old, lot_mid, lot_new):
            _put_batch(
                db_session,
                async_engine_fixture,
                doc_org.id,
                template.id,
                doc_source_location.id,
                Decimal('4'),
                lot_id=lot.id,
            )

        item = _make_fefo_item(
            db_session,
            doc_org.id,
            template.id,
            doc_source_location.id,
            Decimal('12'),
        )
        db_session.commit()

        # Scrap 5 units. FEFO order: OLD-LOT (4 fully) + MID-LOT (1).
        # NEW-LOT untouched.
        _create_scrap(
            client,
            doc_auth_headers,
            source_location_id=doc_source_location.id,
            item_id=item.id,
            template_id=template.id,
            quantity=5,
        )

        assert _quant_quantity(
            db_session, doc_org.id, lot_old.id, doc_source_location.id
        ) == Decimal('0')
        assert _quant_quantity(
            db_session, doc_org.id, lot_mid.id, doc_source_location.id
        ) == Decimal('3')
        assert _quant_quantity(
            db_session, doc_org.id, lot_new.id, doc_source_location.id
        ) == Decimal('4')
