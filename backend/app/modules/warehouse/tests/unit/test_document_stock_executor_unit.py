from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.warehouse._stock_executor_helpers import (
    CorrectionItemMissingError,
)
from app.modules.warehouse.document_stock_executor import (
    _execute_adjustment,
    _execute_correction,
    execute_stock_operations,
)
from app.modules.warehouse.models import DocumentLine

_CORE_API_TARGETS = (
    'app.modules.warehouse._stock_executor_helpers.core_api',
    'app.modules.warehouse._receipt_planning.core_api',
    'app.modules.warehouse._stock_executor_receipt.core_api',
    'app.modules.warehouse._stock_executor_outbound.core_api',
    'app.modules.warehouse._stock_executor_transfer.core_api',
    'app.modules.warehouse._stock_executor_deltas.core_api',
)


def _make_async_db() -> MagicMock:
    """Build a MagicMock ``db`` whose ``.execute`` and ``.scalars`` are awaitable.

    Putaway: the receipt executor now invokes
    ``resolve_putaway_location_async`` which calls ``db.execute``. Older
    tests passed a plain ``MagicMock()`` because no executor path used
    ``db.execute`` synchronously. Now they must opt in.

    Landed costs: the dispatcher asks for the receipt's extra costs
    before posting the first line, and that read is awaited — a synchronous
    ``scalars`` double stops the whole executor with a TypeError that names
    a MagicMock rather than the call that wanted it.
    """
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: []))
    )
    db.scalars = AsyncMock(return_value=MagicMock(all=lambda: [], first=lambda: None))
    # The putaway planner asks the shelf's capacity and mix through scalar
    # reads; the default answer is "no rows" — no limit, mixed products.
    db.scalar = AsyncMock(return_value=None)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # What a posting remembers for the length of its transaction lives on the
    # session's own ``info``; a mocked session needs a real mapping there.
    db.sync_session.info = {}
    return db


def _patch_core_api(mock_core: MagicMock) -> ExitStack:
    """Patch core_api across all stock_executor submodules after the split.

    Every executor branch now emits a StockMove via
    ``core_api.stock_moves.create_async`` — pre-stub it as an AsyncMock
    so the existing unit tests don't need per-test boilerplate. Tests
    that want to assert on the StockMove payload can override the
    attribute on ``mock_core`` after calling this helper.

    Dispatch/scrap/transfer without an explicit batch/serial now
    take the strategy draw planned from the records via
    ``core_api.stock.take_from_the_records_async`` — stub it
    with an empty breakdown by default. Tests that exercise the
    explicit-lot branch override with their own AsyncMock.

    Putaway: the receipt executor calls
    ``resolve_putaway_location_async`` via CoreAPI lookup. Pre-stub
    the AsyncMock target so receipt-time lookups don't blow up on the
    MagicMock db.execute.
    """
    mock_core.stock_moves = MagicMock()
    mock_core.stock_moves.create_async = AsyncMock()
    # The movement pass states the records handed to it beside the
    # movement; tests that care assert on its call.
    mock_core.stock.post_movement_async = AsyncMock()
    # The document locks the stock of every product it names before its
    # first line; there is nothing to lock in a mocked session.
    mock_core.stock.lock_async = AsyncMock()
    # A correction locks its lines' records and the cost layers a removal
    # drains up front; a mocked session holds neither.
    mock_core.items.lock_records_async = AsyncMock()
    mock_core.valuation.lock_open_layers_async = AsyncMock()
    mock_core.stock.take_from_the_records_async = AsyncMock(return_value=[])
    # Adoption posts the stock a cardless record already held into the ledger
    # before the door moves any of it — through the Core's one opening rule.
    # Pre-stubbed for the same reason as the strategy breakdown above; a test
    # about the opening overrides it.
    mock_core.items.post_opening_balance_async = AsyncMock()
    mock_core.valuation.record_unpriced_receipt_async = AsyncMock()
    # Outbound asks the ledger how much stands on the shelf before it takes
    # anything off it. An empty answer means the shelf shows no group, and
    # the record's own quantity decides — which is the shape these unit
    # tests were written against. Tests about the ledger gate say otherwise.
    mock_core.stock.list_quants_async = AsyncMock(return_value=[])
    mock_core.items.list_by_expiry_async = AsyncMock(return_value=[])
    # Where a new record is filed: the receipt asks the product's records
    # what category they carry. A mocked session holds no records, so the
    # answer is None unless a test stubs its own.
    if not isinstance(mock_core.items.inherited_category_async, AsyncMock):
        mock_core.items.inherited_category_async = AsyncMock(return_value=None)
    # the receipt executor resolves the putaway text match keys via
    # category / storage-type lookups — default them to None so unit tests
    # that don't care about putaway keep a clean call surface.
    mock_core.categories.get_by_id_async = AsyncMock(return_value=None)
    mock_core.locations.get_with_type_async = AsyncMock(return_value=None)
    # The planner also resolves shelf names for the lines it decides about.
    mock_core.locations.get_async = AsyncMock(return_value=None)
    # The planner resolves the product name behind a template match even
    # when the line only tops a row up — a read the old code never made on
    # that path. Default to None unless the test stubbed the attribute
    # itself: the open-row tests do, with the template the row is a record
    # of, and a blanket default would overwrite their stub.
    if not isinstance(mock_core.product_templates.get_async, AsyncMock):
        mock_core.product_templates.get_async = AsyncMock(return_value=None)
    # Every executor now states the line's quantity in the product's stock
    # unit before touching anything. These lines name no unit, so the default
    # hands the number back — the real function's own answer for that case.
    mock_core.uoms.to_stock_uom_async = AsyncMock(
        side_effect=lambda _db, _org, _template_id, quantity, _uom_id: quantity
    )

    # A record that predates its card gets one adopted before the outbound
    # executors write the ledger. The default resolves a throwaway card and
    # binds it, so tests about other mechanics keep their legacy-shaped rows
    # without wiring the catalogue; a test about the adoption itself stubs
    # these with the answer it wants (the guard keeps such a stub).
    if not isinstance(mock_core.product_templates.resolve_default_async, AsyncMock):
        mock_core.product_templates.resolve_default_async = AsyncMock(
            return_value=MagicMock(id=uuid4())
        )
    if not isinstance(mock_core.items.bind_template_async, AsyncMock):
        mock_core.items.bind_template_async = AsyncMock(
            side_effect=lambda _db, _org, _item_id, _template_id, **_kw: MagicMock()
        )

    # Every executor reads the record's quantity again under the row lock
    # before it writes one. Without a database there is no lock and nothing
    # else to race, so the locked read is the record the test already set up.
    async def _locked_read(*args: Any, **kwargs: Any) -> Any:
        return await mock_core.items.get_async(*args, **kwargs)

    mock_core.items.get_for_update_async = AsyncMock(side_effect=_locked_read)
    stack = ExitStack()
    for target in _CORE_API_TARGETS:
        stack.enter_context(patch(target, mock_core))
    return stack


def _make_doc(
    *,
    doc_type: str = 'IN',
    org_id: UUID | None = None,
    target_location_id: UUID | None = None,
    source_location_id: UUID | None = None,
    lines: list[Any] | None = None,
    corrects_document_id: UUID | None = None,
    number: str = 'IN/2026/001',
) -> MagicMock:
    doc = MagicMock()
    doc.id = uuid4()
    doc.organization_id = org_id or uuid4()
    doc.type = doc_type
    doc.number = number
    doc.target_location_id = target_location_id
    doc.source_location_id = source_location_id
    doc.lines = lines or []
    doc.corrects_document_id = corrects_document_id
    # A bare MagicMock attribute is truthy, and a document whose stock is
    # already applied executes nothing.
    doc.stock_already_applied = False
    return doc


def _make_line(
    *,
    item_id: UUID | None = None,
    product_template_id: UUID | None = None,
    name: str | None = None,
    brand: str | None = None,
    barcode: str | None = None,
    done_quantity: Decimal = Decimal('5'),
    expected_quantity: Decimal = Decimal('10'),
    uom_id: UUID | None = None,
    unit_price: Decimal | None = None,
    batch_number: str | None = None,
    serial_number: str | None = None,
    expiry_date: date | None = None,
) -> MagicMock:
    line = MagicMock(spec=DocumentLine)
    line.id = uuid4()
    line.item_id = item_id
    line.product_template_id = product_template_id
    line.name = name
    line.brand = brand
    line.barcode = barcode
    line.done_quantity = done_quantity
    line.expected_quantity = expected_quantity
    line.held_quantity = Decimal('0')
    line.source_location_id = None
    line.uom_id = uom_id
    line.unit_price = unit_price
    line.batch_number = batch_number
    line.serial_number = serial_number
    line.expiry_date = expiry_date
    # The putaway planner reads the line's own destination; spec'd mocks
    # leave the attribute unset, which is exactly "no shelf named".
    line.target_location_id = None
    return line


def _make_item(
    *,
    id: UUID | None = None,
    quantity: Decimal = Decimal('10'),
    template_id: UUID | None = None,
    storage_location_id: UUID | None = None,
    name: str = 'Item',
) -> MagicMock:
    item = MagicMock()
    item.id = id or uuid4()
    item.quantity = quantity
    item.template_id = template_id
    item.location_id = storage_location_id
    item.name = name
    # A record of no batch: the receipt tops a record up only with its own.
    item.lot_id = None
    return item


def _make_template(
    *,
    id: UUID | None = None,
    name: str = 'Product',
    brand: str | None = None,
    barcode: str | None = None,
    sku: str | None = None,
    image_url: str | None = None,
    description: str | None = None,
    uom_id: UUID | None = None,
) -> MagicMock:
    tpl = MagicMock()
    tpl.id = id or uuid4()
    tpl.name = name
    tpl.brand = brand
    tpl.barcode = barcode
    tpl.sku = sku
    tpl.image_url = image_url
    tpl.description = description
    # A record opened by a receipt carries the product's stock unit, so the
    # attribute has to be a unit or nothing — a bare MagicMock here would
    # reach the DTO as a stand-in for a UUID.
    tpl.uom_id = uom_id
    return tpl


@pytest.mark.unit
class TestExecuteStockOperations:
    @pytest.mark.asyncio
    async def test_skips_lines_with_zero_done_quantity(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        line = _make_line(done_quantity=Decimal('0'))
        doc = _make_doc(doc_type='IN', lines=[line])
        await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_receives_item_with_existing_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        item = _make_item(quantity=Decimal('10'), storage_location_id=loc_id)
        tpl = _make_template()
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
        )
        doc = _make_doc(doc_type='IN', target_location_id=loc_id, lines=[line])

        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.stock.post_movement_async = AsyncMock()
        mock_core.valuation.record_receipt_async = AsyncMock()

        with _patch_core_api(mock_core):
            await execute_stock_operations(db, doc, user_id)

        # The record's number rides the movement pass: stated inside the
        # stock's locks, where the movement is written.
        mock_core.stock.post_movement_async.assert_awaited_once()
        posted = mock_core.stock.post_movement_async.call_args.kwargs['records']
        assert [str(r.item_id) for r in posted] == [str(item.id)]
        assert posted[0].new_quantity == Decimal('15')

    @pytest.mark.asyncio
    async def test_receives_new_item_from_template(self) -> None:
        db = _make_async_db()
        db.flush = AsyncMock()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        new_item = _make_item(id=uuid4(), storage_location_id=loc_id)
        line = _make_line(
            product_template_id=tpl.id,
            done_quantity=Decimal('3'),
            unit_price=Decimal('5.14'),
        )
        doc = _make_doc(doc_type='IN', target_location_id=loc_id, lines=[line])
        # The price is in the organization's money — a mock attribute would
        # read as some other currency and keep the price off the record.
        line.currency = None
        doc.currency = 'USD'

        mock_core = MagicMock()
        mock_core.product_templates.get_async = AsyncMock(return_value=tpl)
        # Nothing of this product is on the shelf yet, so the line has no
        # record to top up and the receipt creates one.
        mock_core.items.find_stock_row_async = AsyncMock(return_value=None)
        mock_core.items.create_async = AsyncMock(return_value=new_item)
        mock_core.stock.post_movement_async = AsyncMock()
        mock_core.valuation.record_receipt_async = AsyncMock()
        # The receipt asks whose money the price is in before putting it on
        # the record.
        mock_core.organizations.get_async = AsyncMock(
            return_value=SimpleNamespace(currency='USD')
        )

        with _patch_core_api(mock_core):
            await execute_stock_operations(db, doc, user_id)

        mock_core.items.create_async.assert_awaited_once()
        assert line.item_id == new_item.id
        opened = mock_core.items.create_async.call_args.args[2]
        assert opened.purchase_price == Decimal('5.14')

    @pytest.mark.asyncio
    async def test_dispatch_requires_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        line = _make_line(item_id=None, done_quantity=Decimal('5'))
        doc = _make_doc(doc_type='OUT', lines=[line])
        with pytest.raises(
            ValueError, match='Delivery document lines must reference existing items'
        ):
            await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_dispatch_raises_on_insufficient_stock(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        item = _make_item(quantity=Decimal('3'))
        line = _make_line(item_id=item.id, done_quantity=Decimal('5'))
        doc = _make_doc(doc_type='OUT', lines=[line])
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        with _patch_core_api(mock_core):
            with pytest.raises(ValueError, match='Insufficient stock'):
                await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_transfer_requires_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        line = _make_line(item_id=None, done_quantity=Decimal('5'))
        doc = _make_doc(doc_type='INT', lines=[line])
        with pytest.raises(
            ValueError, match='Transfer document lines must reference existing items'
        ):
            await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_scrap_requires_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        line = _make_line(item_id=None, done_quantity=Decimal('2'))
        doc = _make_doc(doc_type='SCRAP', source_location_id=uuid4(), lines=[line])
        with pytest.raises(
            ValueError, match='Scrap document lines must reference existing items'
        ):
            await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_transfer_requires_target_location(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        item = _make_item()
        line = _make_line(item_id=item.id, done_quantity=Decimal('5'))
        doc = _make_doc(
            doc_type='INT',
            target_location_id=None,
            source_location_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        with _patch_core_api(mock_core):
            with pytest.raises(ValueError, match='target location'):
                await execute_stock_operations(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_scrap_decrements_stock(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(quantity=Decimal('10'), template_id=tpl.id)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('3'),
        )
        doc = _make_doc(doc_type='SCRAP', source_location_id=loc_id, lines=[line])
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        # Without an explicit batch/serial the draw is planned from the
        # records (take_from_the_records_async). The default empty
        # breakdown from _patch_core_api covers the call surface.
        mock_core.stock.take_from_the_records_async = AsyncMock(return_value=[])
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            await execute_stock_operations(db, doc, user_id)
        mock_core.stock.take_from_the_records_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scrap_consumes_svl_layer(self) -> None:
        """Scrap must call record_delivery_async to consume SVL (AVCO)."""
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(quantity=Decimal('10'), template_id=tpl.id)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('3'),
        )
        doc = _make_doc(doc_type='SCRAP', source_location_id=loc_id, lines=[line])
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.stock.take_from_the_records_async = AsyncMock(return_value=[])
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            await execute_stock_operations(db, doc, user_id)
        mock_core.valuation.record_delivery_async.assert_awaited_once()
        call_args = mock_core.valuation.record_delivery_async.call_args
        assert call_args.args[2] == tpl.id
        assert call_args.args[3] == Decimal('3')

    @pytest.mark.asyncio
    async def test_scrap_insufficient_stock_leaves_the_stock_untouched(self) -> None:
        """Scrap checks stock sufficiency BEFORE taking any stock.

        Previously the quant (and SVL delivery) were decremented first and
        the item-level sufficiency check ran afterwards — so an insufficient
        scrap could drive the stock negative before raising. Now the guard runs
        before any mutation: neither the draw nor the valuation is called.
        """
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(quantity=Decimal('3'), template_id=tpl.id)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
        )
        doc = _make_doc(doc_type='SCRAP', source_location_id=loc_id, lines=[line])
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            with pytest.raises(ValueError, match='Insufficient stock'):
                await execute_stock_operations(db, doc, user_id)
        mock_core.stock.take_from_the_records_async.assert_not_awaited()
        mock_core.stock.post_movement_async.assert_not_awaited()
        mock_core.valuation.record_delivery_async.assert_not_awaited()


@pytest.mark.unit
class TestExecuteCorrection:
    @pytest.mark.asyncio
    async def test_raises_when_no_corrects_document_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        doc = _make_doc(doc_type='CORRECTION', corrects_document_id=None, lines=[])
        with pytest.raises(ValueError, match='does not name the document it corrects'):
            await _execute_correction(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_raises_when_original_not_found(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        doc = _make_doc(doc_type='CORRECTION', corrects_document_id=uuid4(), lines=[])
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='corrected document.*not found'):
            await _execute_correction(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_correction_requires_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(item_id=None, done_quantity=Decimal('2'))
        doc = _make_doc(
            doc_type='CORRECTION', corrects_document_id=uuid4(), lines=[line]
        )
        with pytest.raises(
            ValueError, match='Correction document lines must reference existing items'
        ):
            await _execute_correction(db, doc, user_id)

    @pytest.mark.asyncio
    async def test_raises_friendly_message_when_item_missing(self) -> None:
        """a correction whose item vanished fails with the product
        name and a hint — not a raw 'Item <uuid> not found' sentence."""
        db = _make_async_db()
        user_id = uuid4()
        tpl = _make_template()
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=uuid4(),
            product_template_id=tpl.id,
            name='Vanished Widget',
            done_quantity=Decimal('2'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=None)
        with _patch_core_api(mock_core):
            with pytest.raises(CorrectionItemMissingError) as exc_info:
                await _execute_correction(db, doc, user_id)
        detail = cast(dict[str, Any], exc_info.value.detail)
        assert detail['code'] == 'CORRECTION_ITEM_MISSING'
        assert detail['product'] == 'Vanished Widget'
        assert 'no longer exists' in detail['message']
        assert str(line.item_id) not in detail['message']

    @pytest.mark.asyncio
    async def test_correction_positive_delta_records_receipt(self) -> None:
        """Correction increasing stock (effective_delta>0) records a receipt SVL."""
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'), template_id=tpl.id, storage_location_id=loc_id
        )
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
            unit_price=Decimal('12.00'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        mock_core.valuation.record_delivery_async = AsyncMock()
        mock_core.valuation.record_unpriced_receipt_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.valuation.record_receipt_async.assert_awaited_once()
        mock_core.valuation.record_delivery_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_correction_negative_delta_records_delivery(self) -> None:
        """Correction decreasing stock (effective_delta<0) consumes SVL via delivery."""
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'), template_id=tpl.id, storage_location_id=loc_id
        )
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('-3'),
            unit_price=Decimal('12.00'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.valuation.record_delivery_async.assert_awaited_once()
        call_args = mock_core.valuation.record_delivery_async.call_args
        assert call_args.args[3] == Decimal('3')
        mock_core.valuation.record_receipt_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_correction_positive_without_price_records_an_unpriced_receipt(
        self,
    ) -> None:
        """A correction raising stock with no unit_price still posts a receipt.

        Through the one receipt call, with no cost: that spelling reaches the
        unpriced policy (the organization's own rate, or unknown), and it is
        the same call that carries the line being reversed.
        """
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'), template_id=tpl.id, storage_location_id=loc_id
        )
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
            unit_price=None,
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        mock_core.valuation.record_delivery_async = AsyncMock()
        mock_core.valuation.record_unpriced_receipt_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.valuation.record_receipt_async.assert_awaited_once()
        posted = mock_core.valuation.record_receipt_async.await_args
        assert posted.args[4] is None  # unit_cost: nobody named a price
        assert posted.kwargs['reverses_line_id'] == line.corrects_line_id
        mock_core.valuation.record_unpriced_receipt_async.assert_not_awaited()
        mock_core.valuation.record_delivery_async.assert_not_awaited()

    # ------------------------------------------------------------------
    # A correction must not create phantom lots
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_correction_does_not_create_phantom_lot(self) -> None:
        """_resolve_lot with create_if_missing=False; no get_or_create."""
        db = _make_async_db()
        user_id = uuid4()
        loc_id = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'), template_id=tpl.id, storage_location_id=loc_id
        )
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
            unit_price=Decimal('12.00'),
            batch_number='LOT-001',
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            target_location_id=loc_id,
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.stock.list_lots_async = AsyncMock(return_value=[])
        mock_core.stock.get_or_create_lot_async = AsyncMock()
        mock_core.valuation.record_receipt_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.stock.get_or_create_lot_async.assert_not_awaited()
        mock_core.stock.list_lots_async.assert_awaited_once()

    # ------------------------------------------------------------------
    # A correction lands where the original landed, not on the record's
    # current shelf — the original line's executed place when it has one, the
    # document's own location otherwise
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_correction_receipt_uses_target_location(self) -> None:
        """No executed place on the original line leaves the doc target."""
        db = _make_async_db()
        user_id = uuid4()
        item_loc = uuid4()
        target_loc = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'),
            template_id=tpl.id,
            storage_location_id=item_loc,
        )
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
            unit_price=Decimal('12.00'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            target_location_id=target_loc,
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.stock.post_movement_async.assert_awaited_once()
        call = mock_core.stock.post_movement_async.call_args
        assert call.kwargs['to_location_id'] == target_loc
        assert call.kwargs['to_location_id'] != item_loc

    @pytest.mark.asyncio
    async def test_correction_lands_where_the_delivery_landed(self) -> None:
        """The original line's executed place beats the document's target.

        A receipt lands the goods with the record it tops up, which is not
        always where its document pointed. Trusting the document put a
        correction's stock on a shelf the delivery never touched, and the
        reconciliation report — which pairs the shelf the records make
        against the movement ledger — named drift nobody caused.
        """
        db = _make_async_db()
        user_id = uuid4()
        item_loc = uuid4()
        target_loc = uuid4()
        landed_loc = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'),
            template_id=tpl.id,
            storage_location_id=item_loc,
        )
        original_line_id = uuid4()
        original = MagicMock()
        original.type = 'IN'
        original.number = 'IN/2026/001'
        original.lines = [
            MagicMock(id=original_line_id, executed_location_id=landed_loc)
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('5'),
            unit_price=Decimal('12.00'),
        )
        line.corrects_line_id = original_line_id
        doc = _make_doc(
            doc_type='CORRECTION',
            target_location_id=target_loc,
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        mock_core.stock.post_movement_async.assert_awaited_once()
        call = mock_core.stock.post_movement_async.call_args
        assert call.kwargs['to_location_id'] == landed_loc
        assert call.kwargs['to_location_id'] != target_loc

    @pytest.mark.asyncio
    async def test_correction_dispatch_uses_source_location(self) -> None:
        """No executed place on a dispatch leaves the doc source."""
        db = _make_async_db()
        user_id = uuid4()
        item_loc = uuid4()
        source_loc = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'),
            template_id=tpl.id,
            storage_location_id=item_loc,
        )
        original = MagicMock()
        original.type = 'OUT'
        original.number = 'OUT/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('3'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            source_location_id=source_loc,
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        call = mock_core.stock.post_movement_async.call_args
        assert call.kwargs['from_location_id'] == source_loc

    # ------------------------------------------------------------------
    # INT correction rebalances source AND target shelves
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_correction_of_int_rebalances_both_shelves(self) -> None:
        """Correcting INT moves the stock on both the source and the target."""
        db = _make_async_db()
        user_id = uuid4()
        source_loc = uuid4()
        target_loc = uuid4()
        tpl = _make_template()
        item = _make_item(
            quantity=Decimal('10'),
            template_id=tpl.id,
            storage_location_id=target_loc,
        )
        original = MagicMock()
        original.type = 'INT'
        original.number = 'INT/2026/001'
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = original
        db.execute = AsyncMock(return_value=mock_result)
        line = _make_line(
            item_id=item.id,
            product_template_id=tpl.id,
            done_quantity=Decimal('-2'),
        )
        doc = _make_doc(
            doc_type='CORRECTION',
            source_location_id=source_loc,
            target_location_id=target_loc,
            corrects_document_id=uuid4(),
            lines=[line],
        )
        mock_core = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_quantity_async = AsyncMock(return_value=item)
        mock_core.valuation.record_receipt_async = AsyncMock()
        mock_core.valuation.record_delivery_async = AsyncMock()
        with _patch_core_api(mock_core):
            await _execute_correction(db, doc, user_id)
        # effective_delta = +1 * -2 = -2
        # target: delta=-2 → a take of 2 off the target's named grain
        assert mock_core.stock.post_movement_async.await_count == 2
        first = mock_core.stock.post_movement_async.await_args_list[0]
        assert first.kwargs['from_location_id'] == target_loc
        assert first.args[3] == Decimal('2')
        # source: delta=+2 → a put of 2 at the source
        second = mock_core.stock.post_movement_async.await_args_list[1]
        assert second.kwargs['to_location_id'] == source_loc
        assert second.args[3] == Decimal('2')
        # SVL should NOT be called for INT corrections (transfers don't touch SVL)
        mock_core.valuation.record_receipt_async.assert_not_awaited()
        mock_core.valuation.record_delivery_async.assert_not_awaited()


@pytest.mark.unit
class TestExecuteAdjustment:
    @pytest.mark.asyncio
    async def test_adjustment_requires_item_id(self) -> None:
        db = _make_async_db()
        user_id = uuid4()
        line = _make_line(item_id=None, done_quantity=Decimal('1'))
        doc = _make_doc(doc_type='ADJUSTMENT', lines=[line])
        with pytest.raises(
            ValueError, match='Adjustment document lines must reference existing items'
        ):
            await _execute_adjustment(db, doc, user_id)


@pytest.mark.asyncio
async def test_the_planner_falls_back_to_the_record_shelf() -> None:
    """The last rung of the putaway ladder, reached nowhere else.

    The decision settles serial → line → rule → document → record. Four of
    those five have integration cover; the fifth cannot, because every
    receipt type is in ``_REQUIRES_TARGET``, so no API call can produce a
    receipt whose document target is null. The rung is a safety net for a
    document that lost its target after validation saw it — and a net with
    nothing measuring it is indistinguishable from dead code, which is how
    such a branch gets deleted by the next reader.

    What it fails on: remove the ``record`` rung and this raises, because
    the decision has no shelf left to name. No database: the planner is
    built directly with no rules, so nothing here touches I/O.
    """
    from app.modules.warehouse._receipt_planning import (
        SOURCE_RECORD,
        ReceiptLocationPlanner,
    )

    shelf_id = uuid4()
    doc = SimpleNamespace(
        organization_id=uuid4(),
        target_location_id=None,
        lines=[],
        type='IN',
    )
    planner = ReceiptLocationPlanner(cast(Any, _make_async_db()), cast(Any, doc))
    named = SimpleNamespace(
        serial_number=None,
        location_id=shelf_id,
        category_id=None,
        template_id=None,
    )

    decision = await planner.decide(named=named, stock_template_id=None)

    assert decision.source == SOURCE_RECORD
    assert decision.location_id == shelf_id
    assert decision.rule_id is None
