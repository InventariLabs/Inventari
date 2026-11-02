"""To do is ordered: decisions, then the overdue, then by day, then undated."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from app.modules.warehouse._schemas_work_items import WorkItemSchema, WorkItemState
from app.modules.warehouse.backorder_cover_service import StockCover
from app.modules.warehouse.work_item_service import _order

_TODAY = date(2026, 10, 20)


def _item(
    key: str,
    kind: str,
    due: date | None,
    state: WorkItemState = 'todo',
    stock_cover: StockCover | None = None,
) -> WorkItemSchema:
    return WorkItemSchema(
        key=key,
        kind=kind,
        state=state,
        source_kind='document',
        source_id=uuid4(),
        due_date=due,
        stock_cover=stock_cover,
    )


def test_decisions_lead_then_the_dated_by_day_then_the_undated_then_the_done() -> None:
    items = [
        _item('d:custom-undated', 'custom', None),
        _item('d:done', 'ship', _TODAY - timedelta(days=9), state='done'),
        _item('d:later', 'receive', _TODAY + timedelta(days=2)),
        _item('d:approve', 'approve', None),
        _item('d:overdue', 'ship', _TODAY - timedelta(days=3)),
        _item('d:backorder', 'backorder', None),
        _item('d:today', 'receive', _TODAY),
    ]

    ordered = [item.key for item in sorted(items, key=_order)]

    assert ordered == [
        'd:approve',
        'd:backorder',
        'd:overdue',
        'd:today',
        'd:later',
        'd:custom-undated',
        'd:done',
    ]


def test_a_backorder_whose_stock_arrived_leads_the_decisions() -> None:
    items = [
        _item('a:approve', 'approve', None),
        _item('b:none', 'backorder', None, stock_cover='none'),
        _item('c:partial', 'backorder', None, stock_cover='partial'),
        _item('z:full', 'backorder', None, stock_cover='full'),
        _item('y:overdue', 'ship', _TODAY - timedelta(days=3)),
    ]

    ordered = [item.key for item in sorted(items, key=_order)]

    assert ordered == [
        'z:full',
        'a:approve',
        'b:none',
        'c:partial',
        'y:overdue',
    ]
