"""An outbound document takes the records the draw plan names.

The draw is planned from the records under the anchors (``plan_draw_async``,
the one-number stock model in ADR-022) and the door writes each
record the plan names — once. The old flow let the quants choose the batches
and then guessed the records back per batch (``_reduce_stock_cache``), which
took the line's own record first inside a batch and read the records without
the lock. Here the records follow the plan's order: oldest record first
within a grain, only what the grain has free of every order's hold.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
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
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    hold,
    shelf_quant,
    sow,
)

_TODAY = datetime.now(UTC).date()


def _in_months(months: int) -> date:
    return _TODAY + timedelta(days=30 * months)


def _make_lot(
    db: Session,
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
    db.add(lot)
    db.flush()
    db.refresh(lot)
    return lot


def _run_out(
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
) -> str:
    """Create + confirm + complete an OUT document. Returns the doc id."""
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number
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
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return doc_id


def _run_scrap(
    client: TestClient,
    headers: dict[str, str],
    *,
    source_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None = None,
    complete: bool = True,
) -> str:
    """Create + confirm (+ complete) a SCRAP document. Returns the doc id."""
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(source_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    if complete:
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def _complete_doc(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text


def _record_quantity(db: Session, record_id: UUID) -> Decimal:
    db.expire_all()
    record = db.get(Item, record_id)
    assert record is not None
    return record.quantity or Decimal('0')


def _quant_quantity(
    db: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    lot_id: UUID | None,
) -> Decimal:
    """What the grain's records hold; a grain whose records are all gone has no row."""
    group = db.scalars(
        select(ShelfRow).where(
            ShelfRow.organization_id == org_id,
            ShelfRow.product_template_id == template_id,
            ShelfRow.storage_location_id == location_id,
            ShelfRow.lot_id.is_not_distinct_from(lot_id),
        )
    ).first()
    return group.quantity if group is not None else Decimal('0')


def test_a_dispatch_takes_the_oldest_record_first_even_when_the_line_names_another(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """One batch, two records: the plan goes by the records' own order.

    The removal order inside a grain is the record's receipt date, then its
    id — not which record the document line happens to name. The old flow
    took the named record first and left the older record's stock to age on
    the shelf past its batch.
    """
    from app.core.testing import ModuleTestHelper

    h = ModuleTestHelper(db_session)
    template = h.create_template(doc_org, name=f'Plan Order {uuid4().hex[:6]}')
    template.removal_strategy = 'FEFO'
    db_session.commit()

    lot = _make_lot(db_session, doc_org.id, template.id, 'LOT-1', _in_months(6))
    older = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('4'),
        lot_id=lot.id,
        backdate_days=30,
    )
    named = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('6'),
        lot_id=lot.id,
    )

    _run_out(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        source_location_id=doc_source_location.id,
        target_location_id=doc_target_location.id,
        item_id=named.id,
        template_id=template.id,
        quantity=4,
    )

    assert _record_quantity(db_session, older.id) == Decimal('0')
    assert _record_quantity(db_session, named.id) == Decimal('6')
    assert _quant_quantity(
        db_session, doc_org.id, template.id, doc_source_location.id, lot.id
    ) == Decimal('6')


def test_a_dispatch_leaves_the_part_another_order_holds_with_its_record(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """A grain with a hold gives only its free part, off its oldest records.

    Ten on the shelf, another order holds four: a dispatch of six takes the
    four free of the oldest record and two of the next, and the held four
    stay where they stand — on their record, their group and their
    reservation row.
    """
    from app.core.testing import ModuleTestHelper

    h = ModuleTestHelper(db_session)
    template = h.create_template(doc_org, name=f'Held Part {uuid4().hex[:6]}')
    template.removal_strategy = 'FEFO'
    db_session.commit()

    lot = _make_lot(db_session, doc_org.id, template.id, 'LOT-1', _in_months(6))
    older = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('4'),
        lot_id=lot.id,
        backdate_days=30,
    )
    named = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('6'),
        lot_id=lot.id,
    )
    hold(
        db_session, async_engine_fixture, template, doc_source_location.id, Decimal('4')
    )

    _run_out(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        source_location_id=doc_source_location.id,
        target_location_id=doc_target_location.id,
        item_id=named.id,
        template_id=template.id,
        quantity=6,
    )

    assert _record_quantity(db_session, older.id) == Decimal('0')
    assert _record_quantity(db_session, named.id) == Decimal('4')
    quant = shelf_quant(
        db_session, doc_org.id, template.id, doc_source_location.id, lot_id=lot.id
    )
    assert quant.quantity == Decimal('4')
    assert quant.reserved_quantity == Decimal('4')


def test_a_dispatch_with_an_explicit_batch_takes_that_batchs_records_in_their_order(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """A named batch draws its own records, in the records' order, and no other."""
    from app.core.testing import ModuleTestHelper

    h = ModuleTestHelper(db_session)
    template = h.create_template(doc_org, name=f'Named Batch {uuid4().hex[:6]}')
    template.removal_strategy = 'FEFO'
    db_session.commit()

    lot_b = _make_lot(db_session, doc_org.id, template.id, 'LOT-B', _in_months(3))
    lot_a = _make_lot(db_session, doc_org.id, template.id, 'LOT-A', _in_months(12))
    b_older = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('3'),
        lot_id=lot_b.id,
        backdate_days=30,
    )
    b_named = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('5'),
        lot_id=lot_b.id,
    )
    a_record = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('8'),
        lot_id=lot_a.id,
    )

    _run_out(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        source_location_id=doc_source_location.id,
        target_location_id=doc_target_location.id,
        item_id=b_named.id,
        template_id=template.id,
        quantity=4,
        batch_number='LOT-B',
    )

    assert _record_quantity(db_session, b_older.id) == Decimal('0')
    assert _record_quantity(db_session, b_named.id) == Decimal('4')
    assert _record_quantity(db_session, a_record.id) == Decimal('8')
    assert _quant_quantity(
        db_session, doc_org.id, template.id, doc_source_location.id, lot_b.id
    ) == Decimal('4')
    assert _quant_quantity(
        db_session, doc_org.id, template.id, doc_source_location.id, lot_a.id
    ) == Decimal('8')


def test_a_scrap_still_takes_a_held_batch_the_line_names(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    """Scrapping is what a recalled batch is for: the plan may not refuse it.

    A guard carried over the rewrite: the strategy branches skip held
    batches, and the named-batch branch must keep skipping the active-lot
    demand — a batch the operator confirmed while it was still good and
    that was recalled before completion still leaves by its name. (Passes
    on the old flow too; it pins the behaviour the plan-based draw could
    silently lose.)
    """
    from app.core.testing import ModuleTestHelper

    h = ModuleTestHelper(db_session)
    template = h.create_template(doc_org, name=f'Recalled Scrap {uuid4().hex[:6]}')
    template.removal_strategy = 'FEFO'
    db_session.commit()

    # Confirmed while the batch was still good — a reservation can only be
    # taken off stock that may be handed out — and recalled before the
    # write-off happened.
    recalled = _make_lot(
        db_session, doc_org.id, template.id, 'LOT-RECALLED', _in_months(6)
    )
    record = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('5'),
        lot_id=recalled.id,
    )
    doc_id = _run_scrap(
        client,
        doc_auth_headers,
        source_location_id=doc_source_location.id,
        item_id=record.id,
        template_id=template.id,
        quantity=3,
        batch_number='LOT-RECALLED',
        complete=False,
    )
    recalled_lot = db_session.get(StockLot, recalled.id)
    assert recalled_lot is not None
    recalled_lot.use_by_date = _in_months(-1)
    db_session.commit()

    _complete_doc(client, doc_auth_headers, doc_id)

    assert _record_quantity(db_session, record.id) == Decimal('2')
    assert _quant_quantity(
        db_session, doc_org.id, template.id, doc_source_location.id, recalled.id
    ) == Decimal('2')


def test_each_record_the_plan_names_is_written_once(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One record update per record the draw takes from, no second pass.

    A guard, not a discriminator: the old flow also wrote each touched
    record once. It pins the invariant the rewrite must keep — the mirror
    step is gone, so the only writer a record gets is the plan's own.
    (Passes on the old flow too.)
    """
    import app.services.items as items_service
    from app.core.testing import ModuleTestHelper

    h = ModuleTestHelper(db_session)
    template = h.create_template(doc_org, name=f'Written Once {uuid4().hex[:6]}')
    template.removal_strategy = 'FEFO'
    db_session.commit()

    lot_b = _make_lot(db_session, doc_org.id, template.id, 'LOT-B', _in_months(3))
    lot_c = _make_lot(db_session, doc_org.id, template.id, 'LOT-C', _in_months(9))
    b_record = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('5'),
        lot_id=lot_b.id,
    )
    c_record = sow(
        db_session,
        async_engine_fixture,
        doc_org,
        template,
        doc_source_location.id,
        Decimal('5'),
        lot_id=lot_c.id,
    )

    written: list[UUID] = []
    real_update = items_service.update_quantity

    def counting_update(*args: Any, **kwargs: Any) -> Any:
        # The facade call carries (db, organization_id, item_id, quantity);
        # the internal one carries the record as ``item``, by keyword or in
        # the second position.
        if 'item' in kwargs:
            written.append(kwargs['item'].id)
        elif len(args) >= 3 and hasattr(args[2], 'quantity'):
            written.append(args[1].id)
        else:
            written.append(args[2])
        return real_update(*args, **kwargs)

    # Both names the writes can be looked up by: the package attribute
    # (what a function-level import reads) and the facade module's own
    # binding (what ``core_api.items.update_quantity_async`` resolves to).
    monkeypatch.setattr(items_service, 'update_quantity', counting_update)
    from app.core.public_api import _items_stock_ops

    monkeypatch.setattr(_items_stock_ops, 'update_quantity', counting_update)

    _run_out(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        source_location_id=doc_source_location.id,
        target_location_id=doc_target_location.id,
        item_id=b_record.id,
        template_id=template.id,
        quantity=7,
    )

    assert sorted(written) == sorted([b_record.id, c_record.id])
    assert _record_quantity(db_session, b_record.id) == Decimal('0')
    assert _record_quantity(db_session, c_record.id) == Decimal('3')
