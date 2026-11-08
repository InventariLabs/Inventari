from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_or_set, org_query_key
from app.core.datetimes import parse_iso_date
from app.core.money import quantise
from app.core.public_api import core_api

from ._assets_service import get_asset_async
from ._schemas_equipment import (
    FleetValuation,
    FleetValuationByCategory,
    ValuationAssetWithoutStatus,
)
from ._serial import serial_of
from .status_machine import resolve_previous_status

DEFAULT_USEFUL_LIFE_YEARS = 5
ZERO = Decimal('0')
HUNDRED = Decimal('100')

# Fleet valuation is an org-wide aggregate — staleness of up to a minute is
# acceptable and the dashboard recomputes it on every entry otherwise.
_VALUATION_CACHE_TTL_SECONDS = 60

# Hard cap for the fleet fetch — mirrors the dashboard aggregation cap;
# 10k covers all realistic equipment deployments.
_MAX_EQUIPMENT_ITEMS = 10000


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def compute_book_value(
    purchase_price: Decimal | None,
    purchase_date: date | str | None,
    useful_life_years: int = DEFAULT_USEFUL_LIFE_YEARS,
    *,
    as_of: date,
) -> dict[str, Any]:
    """Straight-line book value of one asset as at *as_of*.

    *as_of* is required on purpose. It used to default to ``date.today()``,
    which is the server's day: an organization a day ahead of the server saw
    a month of depreciation start late, and nothing on the screen said which
    clock it was reading. The callers pass the organization's own day
    (``core_api.organizations.today_async``), so the fallback has no honest
    value left to hold.
    """
    if not purchase_price or purchase_price <= ZERO:
        return {
            'purchase_price': purchase_price,
            'book_value': ZERO,
            'depreciation_pct': ZERO,
            'useful_life_years': useful_life_years,
            'is_depreciable': False,
        }

    if isinstance(purchase_date, str):
        purchase_date = parse_iso_date(purchase_date)

    # A purchase date and a positive life are the configuration. Without
    # either there is nothing to depreciate from: the asset answers with the
    # price it was bought for and claims no book value, rather than being
    # read as fully depreciated (a zero life meant 100% on day one) or as
    # never depreciated at full price. The interface hides book value and
    # depreciation for it entirely.
    if not purchase_date or useful_life_years <= 0:
        return {
            'purchase_price': purchase_price,
            'book_value': purchase_price if purchase_price else ZERO,
            'depreciation_pct': ZERO,
            'useful_life_years': useful_life_years,
            'is_depreciable': False,
        }

    ref_date = as_of
    total_months = useful_life_years * 12
    elapsed = _months_between(purchase_date, ref_date)

    if elapsed >= total_months:
        depreciation_pct = HUNDRED
        book_value = ZERO
    elif elapsed <= 0:
        depreciation_pct = ZERO
        book_value = purchase_price
    else:
        depreciation_pct = Decimal(elapsed) / Decimal(total_months) * HUNDRED
        book_value = purchase_price * (
            Decimal(total_months - elapsed) / Decimal(total_months)
        )
        book_value = quantise(book_value)

    return {
        'purchase_price': purchase_price,
        'book_value': book_value,
        # Not money.quantise: a percentage of elapsed life is not an amount,
        # and one decimal is what the card shows.
        'depreciation_pct': depreciation_pct.quantize(Decimal('0.1')),
        'useful_life_years': useful_life_years,
        'is_depreciable': True,
    }


def _resolve_useful_life_years(
    eq_meta: dict[str, Any],
    category_field_defs: list[dict[str, Any]] | None,
    module_settings: dict[str, Any],
) -> int:
    """Asset meta → category default → module setting.

    A server must not amortize at the same 5-year rate as a drill; the
    per-asset value wins, the category declaration provides the sensible
    default, and the module setting is the last fallback.
    """
    raw = eq_meta.get('useful_life_years')
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    for field in category_field_defs or []:
        if field.get('key') != 'useful_life_years':
            continue
        default = field.get('default')
        if default is not None:
            try:
                return int(default)
            except (TypeError, ValueError):
                pass
    raw = module_settings.get('default_useful_life_years')
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return DEFAULT_USEFUL_LIFE_YEARS


async def get_asset_valuation_async(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> dict[str, Any] | None:
    # Reads for the card's Info tab survive the archive. The asset's book
    # value stays a fact about the record an archived asset still is.
    item = await get_asset_async(db, org_id, item_id, include_archived=True)
    if not item:
        return None

    module_settings = await core_api.settings.get_async(db, org_id, 'equipment') or {}
    category_field_defs = item.category.field_definitions if item.category else None

    eq_meta = (item.meta_data or {}).get('equipment', {})
    purchase_price = (
        Decimal(str(item.purchase_price)) if item.purchase_price is not None else None
    )
    purchase_date = eq_meta.get('purchase_date')
    useful_life = _resolve_useful_life_years(
        eq_meta, category_field_defs, module_settings
    )

    today = await core_api.organizations.today_async(db, org_id)
    val = compute_book_value(purchase_price, purchase_date, useful_life, as_of=today)
    val['item_id'] = str(item_id)
    val['item_name'] = item.name
    val['serial_number'] = serial_of(item)
    return val


async def get_fleet_valuation_async(db: AsyncSession, org_id: UUID) -> FleetValuation:
    """Org-wide fleet valuation, cached for 60 seconds.

       One ``context_tag='equipment'`` items fetch instead of a loop over
       categories; ``compute_book_value`` stays the per-asset unit and the
    aggregation remains in Python. The currency guard still applies —
       only the organization's currency is summed; assets without a
       purchase price, in a foreign currency, or retired are reported via
       ``excluded_count`` so the counts here can be reconciled with the
       categories catalogue's.
    """

    async def _factory() -> FleetValuation:
        return await _compute_fleet_valuation_async(db, org_id)

    return await cache_get_or_set(  # type: ignore[no-any-return]
        await org_query_key(org_id, 'equipment_fleet_valuation'),
        ttl=_VALUATION_CACHE_TTL_SECONDS,
        factory=_factory,
        deserializer=FleetValuation.model_validate_json,
    )


async def _compute_fleet_valuation_async(
    db: AsyncSession, org_id: UUID
) -> FleetValuation:
    all_items = await core_api.items.list_async(
        db, org_id, context_tag='equipment', limit=_MAX_EQUIPMENT_ITEMS
    )

    # The fleet value is a single number, so only the
    # organization's currency may be summed — mixing USD and PLN would be
    # dishonest arithmetic. Foreign-currency assets are reported, not added.
    organization = await core_api.organizations.get_async(db, org_id)
    org_currency = organization.currency if organization else None

    # One day for the whole fleet, taken from the organization's clock rather
    # than the server's — otherwise two assets in the same valuation could be
    # depreciated as at different days once the loop crossed midnight.
    today = await core_api.organizations.today_async(db, org_id)

    module_settings = await core_api.settings.get_async(db, org_id, 'equipment') or {}
    categories = await core_api.categories.list_async(db, org_id)
    category_field_defs: dict[UUID, list[dict[str, Any]] | None] = {
        c.id: c.field_definitions for c in categories
    }

    total_purchase = ZERO
    total_book = ZERO
    total_depreciation = ZERO
    valued_count = 0
    depreciable_count = 0
    excluded_count = 0
    no_status_assets: list[ValuationAssetWithoutStatus] = []
    by_category: dict[str, dict[str, Any]] = {}

    for item in all_items:
        eq_meta = (item.meta_data or {}).get('equipment', {})
        status = resolve_previous_status(eq_meta.get('equipment_status'))
        if status == 'RETIRED':
            # Retired is out of the valuation by decision, not by accident —
            # but the register still holds the asset, and a count that loses
            # it silently leaves the reader no way to reconcile this number
            # against the categories catalogue's.
            excluded_count += 1
            continue

        purchase_price = (
            Decimal(str(item.purchase_price))
            if item.purchase_price is not None
            else None
        )
        if not purchase_price:
            # An asset without a price is in the register but
            # cannot be summed. Falling out here without a trace let the
            # fleet value sit lower than the register while excluded_count
            # claimed nothing was skipped.
            excluded_count += 1
            continue

        if org_currency and item.currency and item.currency != org_currency:
            excluded_count += 1
            continue

        if not status:
            no_status_assets.append(
                ValuationAssetWithoutStatus(id=item.id, name=item.name)
            )

        purchase_date = eq_meta.get('purchase_date')
        cat_field_defs = (
            category_field_defs.get(item.category_id)
            if item.category_id is not None
            else None
        )
        useful_life = _resolve_useful_life_years(
            eq_meta, cat_field_defs, module_settings
        )
        val = compute_book_value(
            purchase_price, purchase_date, useful_life, as_of=today
        )

        # Purchase value is a fact for every priced asset; book value and
        # depreciation are facts only for the assets configured with a
        # purchase date and a useful life. An unconfigured asset contributes
        # its purchase price and nothing else — no invented zero, and no
        # assumed "not depreciated" full price either. ``depreciable_count``
        # is what the interface reads to decide whether the financial
        # columns have anything to stand on at all.
        total_purchase += purchase_price
        valued_count += 1
        if val['is_depreciable']:
            depreciable_count += 1
            total_book += val['book_value']
            total_depreciation += purchase_price - val['book_value']

        cat_name = getattr(item.category, 'name', None) or 'Unknown'
        cat_code = getattr(item.category, 'code', None)
        if cat_name not in by_category:
            by_category[cat_name] = {
                'category_name': cat_name,
                'category_code': cat_code,
                'purchase_value': ZERO,
                'book_value': ZERO,
                'depreciation': ZERO,
                'asset_count': 0,
                'depreciable_count': 0,
            }
        by_category[cat_name]['purchase_value'] += purchase_price
        by_category[cat_name]['asset_count'] += 1
        if val['is_depreciable']:
            by_category[cat_name]['book_value'] += val['book_value']
            by_category[cat_name]['depreciation'] += purchase_price - val['book_value']
            by_category[cat_name]['depreciable_count'] += 1

    return FleetValuation(
        total_purchase_value=quantise(total_purchase),
        total_book_value=quantise(total_book),
        total_depreciation=quantise(total_depreciation),
        by_category=[
            FleetValuationByCategory(
                category_name=row['category_name'],
                category_code=row['category_code'],
                purchase_value=row['purchase_value'],
                book_value=row['book_value'],
                depreciation=row['depreciation'],
                asset_count=row['asset_count'],
                depreciable_count=row['depreciable_count'],
            )
            for row in by_category.values()
        ],
        asset_count=valued_count,
        depreciable_count=depreciable_count,
        excluded_count=excluded_count,
        no_status_count=len(no_status_assets),
        no_status_assets=no_status_assets,
    )
