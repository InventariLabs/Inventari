"""
Smart alerts and recommendations service.

Generates proactive alerts for forgotten items, missing staples,
and items nearing expiry.
"""

# architecture: allow_direct_db_access
# reason: Complex multi-join alerts with history analysis cannot be expressed through CoreAPI

import statistics
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import ColumnElement

from app.core.module_sdk import general_rows, hidden_module_tags_async
from app.core.public_api import core_api
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory

from .constants import MAX_ANALYTICS_ROWS


def _to_naive(dt: datetime) -> datetime:
    """Drop timezone info so naive/aware datetimes are comparable."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


async def _lot_names_async(
    db: AsyncSession, organization_id: UUID, items: Sequence[Item]
) -> dict[UUID, str]:
    """The batch name of every record among *items* that has one.

    Read per product, through the batches the core lists for it: the records
    an alert names are a week's worth of dates, so the products are few.
    """
    names: dict[UUID, str] = {}
    products = {
        item.template_id
        for item in items
        if item.lot_id is not None and item.template_id is not None
    }
    for product_id in products:
        for lot in await core_api.stock.list_lots_async(
            db, organization_id, product_id
        ):
            names[lot.id] = lot.name
    return names


async def get_smart_alerts_async(  # noqa: C901 - existing complexity/size
    db: AsyncSession, organization_id: UUID
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    # ``shown``: a vertical module's records stay out unless the organization
    # shows module data — an alert leads to a record in the products list,
    # and the family laptop is not one of a household's forgotten groceries.
    today, recent_purchases_since, shown = (
        await core_api.organizations.today_async(db, organization_id),
        await core_api.organizations.window_start_async(db, organization_id, 90),
        general_rows(await hidden_module_tags_async(db, organization_id)),
    )

    # Last touched is max(updated_at, last ItemHistory action): a record
    # somebody consumed from is not stale just because the row itself was
    # not edited. Read in the same query as the records, grouped once.
    # No action filter and no check, on purpose: whatever kind a row is,
    # somebody handled the record, and that is all "touched" means here.
    last_action = (
        select(
            ItemHistory.item_id.label('item_id'),
            func.max(ItemHistory.created_at).label('last_action_at'),
        )
        .where(ItemHistory.organization_id == organization_id)
        .group_by(ItemHistory.item_id)
        .subquery()
    )
    # The candidates are cut at a ceiling, so the cut has to keep the ones
    # the alert is about: the stalest first, by the same "last touched" the
    # loop below measures (GREATEST skips a NULL). Unordered, past the
    # ceiling the alerts came from whichever records the database returned.
    staleness = func.greatest(
        Item.updated_at,
        cast(Item.added_date, DateTime(timezone=True)),
        last_action.c.last_action_at,
    )
    forgotten_rows = (
        await db.execute(
            select(Item, last_action.c.last_action_at)
            .options(joinedload(Item.category))
            .outerjoin(last_action, last_action.c.item_id == Item.id)
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                shown,
            )
            .order_by(staleness.asc().nulls_last(), Item.id)
            .limit(MAX_ANALYTICS_ROWS)
        )
    ).all()

    for item, last_action_at in forgotten_rows:
        candidates: list[datetime] = []
        if item.updated_at is not None:
            candidates.append(_to_naive(item.updated_at))
        if item.added_date is not None:
            candidates.append(datetime.combine(item.added_date, datetime.min.time()))
        if last_action_at is not None:
            candidates.append(_to_naive(last_action_at))

        if not candidates:
            continue
        last_touched: datetime = max(candidates)
        if last_touched.date() > today:
            continue
        days_untouched = (today - last_touched.date()).days
        if days_untouched < 60:
            continue
        alerts.append(
            {
                'type': 'FORGOTTEN_ITEM',
                'severity': 'warning',
                'item_id': str(item.id),
                'item_name': item.name,
                'days_untouched': days_untouched,
                'message_key': 'stats.alerts.forgotten_item',
                'message_params': {'product': item.name, 'days': days_untouched},
                'action': 'view_item',
                'action_param': str(item.id),
            }
        )

    regular_products = (
        await db.execute(
            select(Item.name, func.count(Item.id).label('count'))
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                Item.created_at >= recent_purchases_since,
                shown,
            )
            .group_by(Item.name)
            .having(func.count(Item.id) >= 2)
            .limit(MAX_ANALYTICS_ROWS)
        )
    ).all()

    if regular_products:
        regular_names = [p.name for p in regular_products]

        latest_items = (
            await db.scalars(
                select(Item)
                .where(
                    Item.organization_id == organization_id,
                    Item.is_deleted.is_(False),
                    Item.name.in_(regular_names),
                    shown,
                )
                .order_by(Item.name, Item.created_at.desc())
                .limit(MAX_ANALYTICS_ROWS)
            )
        ).all()
        latest_by_name: dict[str, Item] = {}
        for item in latest_items:
            if item.name not in latest_by_name:
                latest_by_name[item.name] = item

        # Trusts the filter: it is a single equality on the one action that
        # means "this record came in", and only the row's date is read.
        history_records = (
            await db.scalars(
                select(ItemHistory)
                .options(joinedload(ItemHistory.item))
                .join(Item, ItemHistory.item_id == Item.id)
                .where(
                    ItemHistory.organization_id == organization_id,
                    ItemHistory.action == ItemAction.CREATED,
                    Item.name.in_(regular_names),
                )
                .limit(MAX_ANALYTICS_ROWS)
            )
        ).all()
        dates_by_name: dict[str, list[date]] = {}
        for h in history_records:
            if h.item:
                name = h.item.name
                dates_by_name.setdefault(name, []).append(h.created_at.date())

        for product_name in regular_names:
            current = latest_by_name.get(product_name)
            if not current:
                continue

            dates = sorted(dates_by_name.get(product_name, []))
            if len(dates) >= 2:
                intervals = [
                    (dates[i] - dates[i - 1]).days for i in range(1, len(dates))
                ]
                avg_frequency = int(statistics.mean(intervals)) if intervals else 7
                days_since_purchase = (
                    today
                    - (
                        current.created_at.date()
                        if hasattr(current.created_at, 'date')
                        else current.created_at
                    )
                ).days

                if days_since_purchase > avg_frequency * 2:
                    alerts.append(
                        {
                            'type': 'MISSING_STAPLE',
                            'severity': 'info',
                            'item_name': product_name,
                            'product_name': product_name,
                            'last_purchase_days_ago': days_since_purchase,
                            'usual_frequency_days': avg_frequency,
                            'message_key': 'stats.alerts.missing_staple',
                            'message_params': {
                                'product': product_name,
                                'frequency': avg_frequency,
                                'days_since': days_since_purchase,
                            },
                            'action': 'add_to_shopping_list',
                        }
                    )

    alerts.extend(await _expiry_alerts_async(db, organization_id, today, shown))

    return {'alerts': alerts, 'total_alerts': len(alerts)}


async def _expiry_alerts_async(
    db: AsyncSession, organization_id: UUID, today: date, shown: ColumnElement[bool]
) -> list[dict[str, Any]]:
    """One alert per record on the shelves going off within a week, or gone off.

    *shown* is the condition that keeps a vertical module's records out,
    as for the other alerts.
    """
    # Expired and expiring together, worst first: the overview beside these
    # alerts counts both among what needs attention, and stopping the query
    # at today left the one record already spoiled as the one never named.
    # Only what is on the organization's own shelves: a record used up into a
    # virtual place keeps its old date, and is no alert for ever after.
    dated_items = (
        await db.scalars(
            select(Item)
            .options(joinedload(Item.category), joinedload(Item.storage_location))
            .where(
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
                Item.storage_location.has(usage='internal'),
                shown,
                Item.effective_expiry_date.isnot(None),
                Item.effective_expiry_date <= today + timedelta(days=7),
            )
            .order_by(Item.effective_expiry_date.asc())
            .limit(MAX_ANALYTICS_ROWS)
        )
    ).all()

    dated: list[dict[str, Any]] = []
    # Two records of one product going off on one day read the same sentence
    # twice; where each one lies, and its batch, is what tells them apart.
    lot_names = await _lot_names_async(db, organization_id, dated_items)
    for item in dated_items:
        if item.effective_expiry_date is None:
            continue
        days_until_expiry = (item.effective_expiry_date - today).days
        # Today's date has not expired yet (see app.services.items.expiry).
        expired = days_until_expiry < 0
        dated.append(
            {
                'type': 'EXPIRED' if expired else 'EXPIRING_SOON',
                'severity': 'critical' if days_until_expiry <= 2 else 'warning',
                'item_id': str(item.id),
                'item_name': item.name,
                'expiry_date': item.effective_expiry_date.isoformat(),
                'days_until_expiry': days_until_expiry,
                'location_name': item.storage_location_name,
                'lot_name': lot_names.get(item.lot_id) if item.lot_id else None,
                'message_key': (
                    'stats.alerts.expired' if expired else 'stats.alerts.expiring_soon'
                ),
                'message_params': {
                    'product': item.name,
                    'days': days_until_expiry,
                    'date': item.effective_expiry_date.strftime('%d.%m.%Y'),
                },
                'action': 'view_item',
                'action_param': str(item.id),
            }
        )
    return dated
