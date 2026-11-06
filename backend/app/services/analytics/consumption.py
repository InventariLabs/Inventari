"""Consumption (usage + disposal) read-model.

Quantities come from ItemHistory, which records every such event whether or
not the record has a product template. Values come from the valuation
ledger, where an outflow is priced once, at the moment it happens, and never
recomputed — see ``_outflow_value``. Domain-neutral: tracks how stock is used
and wasted across food, equipment, and warehouse verticals.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    ConsumptionItemDTO,
    ConsumptionStatsDTO,
)
from app.core.db_utils import in_ids
from app.core.logging import get_logger
from app.core.module_ownership import general_rows, hidden_module_tags_async
from app.models import Category, Item, ItemHistory
from app.models.item_history import CONSUMPTION_ACTIONS, DISPOSAL_ACTIONS
from app.services.analytics._outflow_value import (
    consumed_value_by_item_async,
    wasted_value_by_item_async,
    window_is_valued_async,
)
from app.services.storage._queries import list_storage_ids_async

from ._common import org_window_start_async, rounded

logger = get_logger(__name__)

# What each history action is to this report. The query below is filtered to
# these actions, deliberately derived from the mapping: widening the filter
# must not widen what the mapping pretends to know.
_KIND_OF_ACTION: dict[str, str] = {
    **dict.fromkeys(CONSUMPTION_ACTIONS, 'consumed'),
    **dict.fromkeys(DISPOSAL_ACTIONS, 'wasted'),
}
_QUERIED_ACTIONS: tuple[str, ...] = tuple(_KIND_OF_ACTION)


def _top_ten(by_product: dict[str, dict], measure: str) -> list[dict]:
    """The ten products largest by *measure*; equal ones in the order of their names.

    The lines come out of a ``GROUP BY`` in no order of their own, so a
    ranking by the figure alone left a tie at the tenth place to whatever
    order the database returned them in, and the same window could name a
    different tenth product on the next reading. The name is what the report
    rolls records up by, so the figure and then the name is a total order.
    """
    return sorted(
        by_product.values(),
        key=lambda line: (-line[measure], line['name'].casefold(), line['name']),
    )[:10]


async def get_consumption_stats_async(
    db: AsyncSession, organization_id: UUID, days: int = 30
) -> ConsumptionStatsDTO:
    """Usage and disposal aggregates over the last ``days`` days."""
    storage_ids = await list_storage_ids_async(db, organization_id)
    if not storage_ids:
        return ConsumptionStatsDTO(
            most_consumed=[],
            most_wasted=[],
            waste_event_rate=0.0,
            total_consumed_value=0.0,
            total_wasted_value=0.0,
            consumption_by_category=[],
        )

    date_from = await org_window_start_async(db, organization_id, days)
    # A vertical module's records stay out unless the organization shows
    # module data, as they stay out of the products list.
    hidden = await hidden_module_tags_async(db, organization_id)

    # Summed where the rows live: one line per record and kind, however many
    # events the window holds. The quantity is ``qty`` — the key the consume
    # and discard path actually writes; a row without it adds nothing but
    # still counts as an event. ``->>`` reads it straight out of the JSON
    # column, so nothing is parsed row by row in Python.
    #
    # The organization filter is what lets the window ride
    # ``ix_item_history_org_action_created``; the storage filter keeps the
    # report to records that are on the organization's shelves.
    quantity = func.coalesce(func.sum(ItemHistory.changes['qty'].as_float()), 0.0)
    rows = (
        await db.execute(
            select(
                ItemHistory.action,
                ItemHistory.item_id,
                Item.name,
                Category.name.label('category_name'),
                Category.code.label('category_code'),
                quantity.label('quantity'),
                func.count().label('events'),
            )
            .join(Item, ItemHistory.item_id == Item.id)
            .outerjoin(Category, Item.category_id == Category.id)
            .where(
                ItemHistory.organization_id == organization_id,
                ItemHistory.action.in_(_QUERIED_ACTIONS),
                ItemHistory.created_at >= date_from,
                in_ids(Item.storage_location_id, storage_ids),
                general_rows(hidden),
            )
            .group_by(
                ItemHistory.action,
                ItemHistory.item_id,
                Item.name,
                Category.name,
                Category.code,
            )
        )
    ).all()

    # The kind of a line is the mapping's to decide, not the WHERE clause's:
    # the filter only spares the database the rows nobody asked about, so a
    # line it lets through that the mapping cannot name is left out — and
    # said so, or a new kind would vanish from the report unnoticed.
    by_kind: dict[str, list[Any]] = {'consumed': [], 'wasted': []}
    skipped: dict[str, int] = {}
    for row in rows:
        kind = _KIND_OF_ACTION.get(row.action)
        if kind is None:
            skipped[row.action] = skipped.get(row.action, 0) + row.events
            continue
        by_kind[kind].append(row)
    if skipped:
        logger.warning(
            'consumption report skipped history rows it cannot name: %s', skipped
        )

    # The ledger, once per report rather than once per row.
    consumed_value = await consumed_value_by_item_async(db, organization_id, date_from)
    wasted_value = await wasted_value_by_item_async(db, organization_id, date_from)

    def _aggregate(
        rows: Sequence[Any], value_by_item: dict[UUID, Decimal]
    ) -> tuple[dict[str, dict], Decimal, int]:
        """Roll the per-record lines up per product, with the ledger's value.

        A record contributes its value once, on the first line that names
        it: the ledger already summed every outflow that record had in the
        window, and adding it per line would multiply it by the number of
        vocabularies its events were written in.
        """
        by_product: dict[str, dict] = {}
        counted: set = set()
        total = Decimal('0')
        events = 0
        for record in rows:
            name = record.name
            by_product.setdefault(
                name,
                {
                    'name': name,
                    'category': record.category_name or 'Other',
                    'category_code': record.category_code,
                    'quantity': 0.0,
                    'value': Decimal('0'),
                },
            )
            by_product[name]['quantity'] += float(record.quantity)
            events += record.events
            if record.item_id not in counted:
                counted.add(record.item_id)
                value = value_by_item.get(record.item_id, Decimal('0'))
                by_product[name]['value'] += value
                total += value
        return by_product, total, events

    consumed_by_product, total_consumed_value, consumed_events = _aggregate(
        by_kind['consumed'], consumed_value
    )
    wasted_by_product, total_wasted_value, wasted_events = _aggregate(
        by_kind['wasted'], wasted_value
    )

    most_consumed = _top_ten(consumed_by_product, 'quantity')
    most_wasted = _top_ten(wasted_by_product, 'value')

    total_events = consumed_events + wasted_events
    waste_event_rate = wasted_events / total_events if total_events > 0 else 0.0

    # Zero and "no idea" are different answers. Before the ledger kept the
    # value of an outflow there is nothing to read, and there is no honest way
    # to reconstruct it — so say so instead of printing a confident 0.00.
    valued = await window_is_valued_async(db, organization_id, date_from)

    return ConsumptionStatsDTO(
        most_consumed=[
            ConsumptionItemDTO(**{**item, 'value': rounded(item['value'])})
            for item in most_consumed
        ],
        most_wasted=[
            ConsumptionItemDTO(**{**item, 'value': rounded(item['value'])})
            for item in most_wasted
        ],
        waste_event_rate=waste_event_rate,
        total_consumed_value=rounded(total_consumed_value) if valued else None,
        total_wasted_value=rounded(total_wasted_value) if valued else None,
        consumption_by_category=[],
    )
