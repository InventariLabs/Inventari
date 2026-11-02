from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.warehouse._picking_helpers import (
    _assign_optimized_pick_order_async,
    _assign_pick_group_async,
    _get_active_session_async,
    _resolve_bin_location_async,
    _resolve_lot_name,
    _resolve_product_name,
    _resolve_uom_symbol,
    get_pick_session_async,
    list_pick_sessions_for_document_async,
    start_pick_session_async,
)
from app.modules.warehouse._wms_session_ops import SessionHeldByOtherUserError
from app.modules.warehouse.models import DocumentStatus

_UNSET = object()


def _make_line(
    *,
    has_product_template: bool = True,
    product_template: MagicMock | None = None,
    item: MagicMock | None = None,
    batch_number: str | None = None,
    serial_number: str | None = None,
    uom: MagicMock | None = None,
    expected_quantity: Decimal = Decimal('10'),
    line_number: int = 1,
    name: str = 'Widget',
    sku: object = _UNSET,
) -> MagicMock:
    line = MagicMock()
    line.id = uuid4()
    line.product_template_id = uuid4() if has_product_template else None
    line.product_template = product_template
    line.item = item
    # `DocumentLine.sku` is a property on the real model; a MagicMock would
    # answer every attribute with a truthy mock, so spell it out here.
    if sku is _UNSET:
        line.sku = product_template.sku if product_template is not None else None
    else:
        line.sku = sku
    line.source_location_id = None
    line.batch_number = batch_number
    line.serial_number = serial_number
    line.uom = uom
    line.expected_quantity = expected_quantity
    line.line_number = line_number
    line.name = name
    return line


def _make_doc(
    *,
    doc_type: str = 'OUT',
    status: str = DocumentStatus.CONFIRMED.value,
    source_location_id: object = _UNSET,
    lines: list[MagicMock] | None = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = uuid4()
    doc.organization_id = uuid4()
    doc.type = doc_type
    doc.status = status
    doc.source_location_id = (
        uuid4() if source_location_id is _UNSET else source_location_id
    )
    doc.lines = lines or []
    return doc


@pytest.mark.unit
class TestResolveProductName:
    def test_from_product_template(self) -> None:
        tmpl = MagicMock()
        tmpl.name = 'Product A'
        line = _make_line(product_template=tmpl)
        assert _resolve_product_name(line) == 'Product A'

    def test_from_item_fallback(self) -> None:
        item = MagicMock()
        item.name = 'Item B'
        line = _make_line(has_product_template=False, product_template=None, item=item)
        assert _resolve_product_name(line) == 'Item B'

    def test_from_line_name_fallback(self) -> None:
        line = _make_line(has_product_template=False, product_template=None, item=None)
        line.name = 'Line C'
        assert _resolve_product_name(line) == 'Line C'

    def test_prefers_product_template_over_item(self) -> None:
        tmpl = MagicMock()
        tmpl.name = 'Template'
        item = MagicMock()
        item.name = 'Item'
        line = _make_line(product_template=tmpl, item=item)
        assert _resolve_product_name(line) == 'Template'


@pytest.mark.unit
class TestResolveLotName:
    def test_from_batch_number(self) -> None:
        line = _make_line(batch_number='LOT-001', serial_number='SN-001')
        assert _resolve_lot_name(line) == 'LOT-001'

    def test_from_serial_number_fallback(self) -> None:
        line = _make_line(batch_number=None, serial_number='SN-001')
        assert _resolve_lot_name(line) == 'SN-001'

    def test_returns_none_when_no_lot(self) -> None:
        line = _make_line(batch_number=None, serial_number=None)
        assert _resolve_lot_name(line) is None


@pytest.mark.unit
class TestResolveUomSymbol:
    def test_from_uom(self) -> None:
        uom = MagicMock()
        uom.symbol = 'kg'
        line = _make_line(uom=uom)
        assert _resolve_uom_symbol(line) == 'kg'

    def test_returns_none_when_no_uom(self) -> None:
        line = _make_line(uom=None)
        assert _resolve_uom_symbol(line) is None


@pytest.mark.unit
class TestGetActiveSessionAsync:
    @pytest.mark.asyncio
    async def test_returns_session_when_found(self) -> None:
        db = MagicMock()
        session = MagicMock()
        session.status = 'active'
        db.scalar = AsyncMock(return_value=session)
        result = await _get_active_session_async(db, uuid4(), uuid4())
        assert result == session

    @pytest.mark.asyncio
    async def test_raises_when_not_found(self) -> None:
        db = MagicMock()
        db.scalar = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='active session was not found'):
            await _get_active_session_async(db, uuid4(), uuid4())


@pytest.mark.unit
class TestAssignPickGroupAsync:
    @pytest.mark.asyncio
    async def test_returns_no_group_when_no_product_template(self) -> None:
        db = MagicMock()
        line = _make_line(has_product_template=False)
        doc = _make_doc()
        result = await _assign_pick_group_async(db, uuid4(), line, doc)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_the_group_and_the_lot(self) -> None:
        db = MagicMock()
        group = MagicMock()
        group.anchor_id = uuid4()
        group.lot_id = uuid4()
        group.expiry_date = date(2026, 10, 25)
        line = _make_line()
        doc = _make_doc()
        with (
            patch(
                'app.modules.warehouse._picking_helpers.core_api',
            ) as mock_api,
            patch(
                'app.modules.warehouse._picking_helpers.lot_covers_async',
                AsyncMock(return_value=True),
            ),
        ):
            mock_api.stock.find_best_pick_group_for_picking_async = AsyncMock(
                return_value=group
            )
            mock_api.stock.list_lots_async = AsyncMock(
                return_value=[SimpleNamespace(id=group.lot_id, name='LOT-7')]
            )
            result = await _assign_pick_group_async(db, uuid4(), line, doc)
        assert result == {
            'anchor_id': group.anchor_id,
            'lot_id': group.lot_id,
            'expiry_date': date(2026, 10, 25),
            'planned_lot_name': 'LOT-7',
        }
        assert (
            mock_api.stock.find_best_pick_group_for_picking_async.await_args.kwargs[
                'except_document_id'
            ]
            == doc.id
        )

    @pytest.mark.asyncio
    async def test_plans_no_lot_when_it_cannot_give_the_whole_line(self) -> None:
        db = MagicMock()
        group = MagicMock()
        group.anchor_id = uuid4()
        group.lot_id = uuid4()
        group.expiry_date = date(2026, 10, 25)
        with (
            patch('app.modules.warehouse._picking_helpers.core_api') as mock_api,
            patch(
                'app.modules.warehouse._picking_helpers.lot_covers_async',
                AsyncMock(return_value=False),
            ),
        ):
            mock_api.stock.find_best_pick_group_for_picking_async = AsyncMock(
                return_value=group
            )
            result = await _assign_pick_group_async(
                db, uuid4(), _make_line(), _make_doc()
            )
        # no batch is planned, so no date is promised either
        assert result == {
            'anchor_id': group.anchor_id,
            'lot_id': None,
            'expiry_date': None,
        }

    @pytest.mark.asyncio
    async def test_returns_no_group_when_the_shelf_is_empty(self) -> None:
        db = MagicMock()
        line = _make_line()
        doc = _make_doc()
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as mock_api:
            mock_api.stock.find_best_pick_group_for_picking_async = AsyncMock(
                return_value=None
            )
            result = await _assign_pick_group_async(db, uuid4(), line, doc)
        assert result == {}


@pytest.mark.unit
class TestLineTemplateAndLocationFallback:
    @pytest.mark.asyncio
    async def test_uses_item_template_when_line_has_none(self) -> None:
        db = MagicMock()
        template_id = uuid4()
        item = MagicMock()
        item.template_id = template_id
        item.location_id = None
        line = _make_line(has_product_template=False, item=item)
        doc = _make_doc()
        group = MagicMock()
        group.anchor_id = uuid4()
        group.lot_id = None
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as mock_api:
            mock_api.stock.find_best_pick_group_for_picking_async = AsyncMock(
                return_value=group
            )
            result = await _assign_pick_group_async(db, uuid4(), line, doc)
            called_template = (
                mock_api.stock.find_best_pick_group_for_picking_async.await_args.args[2]
            )
        assert result['anchor_id'] == group.anchor_id
        assert called_template == template_id

    @pytest.mark.asyncio
    async def test_falls_back_to_item_location_when_doc_has_none(self) -> None:
        db = MagicMock()
        location_id = uuid4()
        item = MagicMock()
        item.template_id = uuid4()
        item.location_id = location_id
        line = _make_line(has_product_template=False, item=item)
        doc = _make_doc(source_location_id=None)
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as mock_api:
            mock_api.stock.find_best_pick_group_for_picking_async = AsyncMock(
                return_value=None
            )
            await _assign_pick_group_async(db, uuid4(), line, doc)
            called_location = (
                mock_api.stock.find_best_pick_group_for_picking_async.await_args.args[3]
            )
        assert called_location == location_id


def _walk_row(
    bin_location: str | None, location: MagicMock | None
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """A session line with its document line and document, as the pass reads them."""
    pick_line = MagicMock()
    pick_line.id = uuid4()
    pick_line.bin_location = bin_location
    pick_line.product_name = 'Product'
    pick_line.expected_quantity = Decimal('1')
    pick_line.lot_name = None
    line = MagicMock()
    line.item = None
    line.product_template_id = None
    line.source_location_id = None
    doc = MagicMock()
    doc.source_location_id = location.id if location is not None else None
    return pick_line, line, doc


def _shelf(code: str, sequence: int | None) -> MagicMock:
    loc = MagicMock()
    loc.id = uuid4()
    loc.parent_id = None
    loc.sequence = sequence
    loc.short_code = code
    loc.name = code
    return loc


@pytest.mark.unit
class TestAssignOptimizedPickOrderAsync:
    @pytest.mark.asyncio
    async def test_sorts_lines_by_code_when_nothing_is_numbered(self) -> None:
        zzz, aaa = _shelf('ZZZ', None), _shelf('AAA', None)
        rows = [_walk_row('ZZZ', zzz), _walk_row('AAA', aaa), _walk_row(None, None)]
        db = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(all=lambda: rows))
        by_id = {zzz.id: zzz, aaa.id: aaa}
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as api:
            api.locations.get_async = AsyncMock(
                side_effect=lambda _db, _org, loc_id: by_id.get(loc_id)
            )
            await _assign_optimized_pick_order_async(db, uuid4())
        assert [row[0].pick_order for row in rows] == [1, 0, 2]

    @pytest.mark.asyncio
    async def test_a_line_without_a_location_comes_last(self) -> None:
        numbered = _shelf('A1', 5)
        rows = [_walk_row('loose', None), _walk_row('A1', numbered)]
        db = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(all=lambda: rows))
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as api:
            api.locations.get_async = AsyncMock(return_value=numbered)
            await _assign_optimized_pick_order_async(db, uuid4())
        assert [row[0].pick_order for row in rows] == [1, 0]


@pytest.mark.unit
class TestResolveBinLocationAsync:
    @pytest.mark.asyncio
    async def test_combines_location_and_sku(self) -> None:
        db = MagicMock()
        loc = MagicMock()
        loc.short_code = 'A1'
        loc.name = 'Shelf A'
        tmpl = MagicMock()
        tmpl.sku = 'SKU-001'
        line = _make_line(product_template=tmpl)
        doc = _make_doc()
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as mock_api:
            mock_api.locations.get_async = AsyncMock(return_value=loc)
            result = await _resolve_bin_location_async(db, line, doc, uuid4())
        # The code gets a worker to the shelf; the name is how the shelf is
        # spoken everywhere else in the app, and the row showed only the code.
        assert result == 'A1 · Shelf A / SKU-001'

    @pytest.mark.asyncio
    async def test_returns_none_when_no_location(self) -> None:
        db = MagicMock()
        line = _make_line(has_product_template=False)
        doc = _make_doc(source_location_id=None)
        result = await _resolve_bin_location_async(db, line, doc, uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_name_when_no_short_code(self) -> None:
        db = MagicMock()
        loc = MagicMock()
        loc.short_code = None
        loc.name = 'Shelf B'
        line = _make_line(product_template=MagicMock(sku=None))
        doc = _make_doc()
        with patch(
            'app.modules.warehouse._picking_helpers.core_api',
        ) as mock_api:
            mock_api.locations.get_async = AsyncMock(return_value=loc)
            result = await _resolve_bin_location_async(db, line, doc, uuid4())
        assert result == 'Shelf B'


@pytest.mark.unit
class TestGetPickSessionAsync:
    @pytest.mark.asyncio
    async def test_returns_session(self) -> None:
        db = MagicMock()
        session = MagicMock()
        db.scalar = AsyncMock(return_value=session)
        result = await get_pick_session_async(db, uuid4(), uuid4())
        assert result == session

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        db = MagicMock()
        db.scalar = AsyncMock(return_value=None)
        result = await get_pick_session_async(db, uuid4(), uuid4())
        assert result is None


@pytest.mark.unit
class TestListPickSessionsForDocumentAsync:
    @pytest.mark.asyncio
    async def test_returns_sessions_list(self) -> None:
        db = MagicMock()
        sessions = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_result.all.return_value = sessions
        db.scalars = AsyncMock(return_value=mock_result)
        result = await list_pick_sessions_for_document_async(db, uuid4(), uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.scalars = AsyncMock(return_value=mock_result)
        result = await list_pick_sessions_for_document_async(db, uuid4(), uuid4())
        assert result == []


@pytest.mark.unit
class TestStartPickSessionAsync:
    @pytest.fixture(autouse=True)
    def _no_profile(self) -> Generator[None]:
        """Unit tests mock the DB session, so the profile read would fail."""
        with patch(
            'app.modules.warehouse._wms_session_ops.get_profile',
            new_callable=AsyncMock,
            return_value=None,
        ):
            yield

    @pytest.mark.asyncio
    async def test_raises_when_doc_not_found(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='document was not found'):
            await start_pick_session_async(db, uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_doc_not_confirmed(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match='document was not found'):
            await start_pick_session_async(db, uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_active_session_exists(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        doc = _make_doc(status=DocumentStatus.CONFIRMED.value)
        existing = MagicMock()
        existing.status = 'active'
        held_id = uuid4()
        existing.id = held_id
        db.scalar = AsyncMock(side_effect=[doc, existing])
        with (
            patch('app.modules.warehouse._wms_session_ops.core_api') as core_api,
            # Somebody is scanning in it now: a session in use is not released.
            patch(
                'app.modules.warehouse._wms_session_ops.session_released_async',
                AsyncMock(return_value=False),
            ),
        ):
            # The holder is unresolvable in this unit fixture — the refusal
            # still speaks, with the fallback name.
            core_api.users.get_async = AsyncMock(return_value=None)
            with pytest.raises(
                SessionHeldByOtherUserError,
                match='Another user has an active session',
            ) as excinfo:
                await start_pick_session_async(db, uuid4(), uuid4(), uuid4())
        assert excinfo.value.session_id == held_id
        assert excinfo.value.owner == 'unknown'

    @pytest.mark.asyncio
    async def test_raises_for_unsupported_doc_type(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        doc = _make_doc(doc_type='IN', status=DocumentStatus.CONFIRMED.value)
        db.scalar = AsyncMock(side_effect=[doc, None])
        db.flush = AsyncMock()
        with pytest.raises(ValueError, match='does not handle'):
            await start_pick_session_async(db, uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_creates_session_for_out_doc(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        line = _make_line()
        doc = _make_doc(
            doc_type='OUT', status=DocumentStatus.CONFIRMED.value, lines=[line]
        )
        # The document, then no open session and no finished one.
        db.scalar = AsyncMock(side_effect=[doc, None, None])
        with (
            patch(
                'app.modules.warehouse._picking_helpers._assign_pick_group_async',
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                'app.modules.warehouse._picking_helpers._resolve_bin_location_async',
                new_callable=AsyncMock,
                return_value='A1',
            ),
            patch(
                'app.modules.warehouse._picking_helpers._assign_optimized_pick_order_async',
                new_callable=AsyncMock,
            ),
        ):
            result = await start_pick_session_async(db, doc.id, uuid4(), uuid4())
        assert result is not None
        assert db.add.call_count >= 1
        db.commit.assert_not_awaited()  # the request commits, not the service

    @pytest.mark.asyncio
    async def test_builds_line_for_item_only_line(self) -> None:
        """A line the scanner built carries ``item_id`` and no template.

        Skipping it left the picker staring at an empty session over a
        document that plainly had a line in it.
        """
        db = MagicMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        item = MagicMock()
        item.name = 'Item B'
        item.template_id = None
        line = _make_line(has_product_template=False, item=item)
        doc = _make_doc(
            doc_type='WZ', status=DocumentStatus.CONFIRMED.value, lines=[line]
        )
        # The document, then no open session and no finished one.
        db.scalar = AsyncMock(side_effect=[doc, None, None])
        with (
            patch(
                'app.modules.warehouse._picking_helpers._assign_pick_group_async',
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                'app.modules.warehouse._picking_helpers._resolve_bin_location_async',
                new_callable=AsyncMock,
            ),
            patch(
                'app.modules.warehouse._picking_helpers._assign_optimized_pick_order_async',
                new_callable=AsyncMock,
            ),
        ):
            result = await start_pick_session_async(db, doc.id, uuid4(), uuid4())
        assert result is not None
        # the session itself plus one pick line
        assert db.add.call_count == 2
