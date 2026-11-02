"""Pure analysis helpers for purchase pattern detection.

Extracted from _purchase_service.py to keep it under the 400 LOC quality
gate. These functions are pure (no DB access) and shared by both the sync
and async purchase-pattern entry points.

The sums arrive from SQL as ``Decimal`` and stay that way until the last
step: every figure leaves through ``rounded``, which rounds half away from
zero like every document line and cost layer, so a total on this report is
the total the valuation engine would state for the same rows. Casting to
float first and calling ``round`` on it used to lose a cent on exactly the
halves — 2.275 sits a hair under the half in binary.
"""

from decimal import Decimal
from typing import Any

from app.core.money import quantise

ZERO = Decimal('0')
#: The analysis window is about six months; annualised savings scale by this.
ANNUALISATION = Decimal(365) / Decimal(180)
BULK_PRICE_SHARE = Decimal('0.85')
BULK_SAVINGS_SHARE = Decimal('0.15')


def rounded(value: Decimal | float, places: int = 2) -> float:
    """A figure for the report: rounded half away from zero, then a float.

    The response fields are floats — estimates for reading — but the float
    is made from a correctly rounded Decimal, not rounded as a float.
    """
    return float(quantise(Decimal(str(value)), places))


def analyze_seasonality(
    product_purchases: dict[str, Any],
) -> list[dict[str, Any]]:
    seasonal: list[dict[str, Any]] = []

    for product_name, data in product_purchases.items():
        if len(data['purchases']) >= 4:
            monthly_counts: dict[str, int] = {}
            for purchase_date in data['purchases']:
                month_key = purchase_date.strftime('%m')
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1

            if max(monthly_counts.values()) >= 3:
                peak_months = [m for m, c in monthly_counts.items() if c >= 2]
                peak_purchases = [
                    p for p in data['purchases'] if p.strftime('%m') in peak_months
                ]
                off_purchases = [
                    p for p in data['purchases'] if p.strftime('%m') not in peak_months
                ]
                avg_peak = (
                    data['total_price'] / len(peak_purchases)
                    if peak_months and peak_purchases
                    else ZERO
                )
                avg_off = (
                    data['total_price'] / len(off_purchases)
                    if peak_months and off_purchases
                    else ZERO
                )

                total_qty: Decimal = data.get('total_quantity', ZERO)
                num_months = len(monthly_counts) or 1
                peak_month_str = peak_months[0] if peak_months else None
                avg_quantity = rounded(total_qty / num_months) if total_qty else 0.0
                peak_qty = (
                    rounded(total_qty * len(peak_purchases) / len(data['purchases']))
                    if data['purchases'] and total_qty
                    else 0.0
                )
                # A season of buying nothing is no season: records whose
                # quantity sums to zero have purchase dates but no peak, and
                # were listed with "Peak quantity: 0".
                if not peak_qty:
                    continue
                # Seasonality is peak measured against off-season. With every
                # purchase inside the peak months there is no off-season to
                # measure against — which is what one month of history looks
                # like, and it used to be reported as 100% for everything.
                seasonality_score = (
                    rounded((avg_peak - avg_off) / avg_off) if avg_off > 0 else None
                )

                seasonal.append(
                    {
                        'name': product_name,
                        'peak_months': peak_months,
                        'avg_monthly_spend_peak': rounded(avg_peak),
                        'avg_monthly_spend_off_season': rounded(avg_off),
                        'peak_month': peak_month_str,
                        'peak_quantity': peak_qty,
                        'average_quantity': avg_quantity,
                        'seasonality_score': seasonality_score,
                    }
                )

    return seasonal[:5]


def find_bulk_opportunities(
    product_purchases: dict[str, Any],
) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []

    for product_name, data in product_purchases.items():
        if len(data['purchases']) >= 3 and data['total_quantity'] > 0:
            avg_quantity = data['total_quantity'] / len(data['purchases'])
            avg_price_per_unit = data['total_price'] / data['total_quantity']

            if avg_quantity < Decimal('0.5') and avg_price_per_unit > 20:
                avg_unit_price = (
                    data['total_price'] / len(data['purchases'])
                    if data['purchases']
                    else ZERO
                )
                opportunities.append(
                    {
                        'product': product_name,
                        'brand': data.get('brand') or None,
                        'current_avg_purchase_kg': rounded(avg_quantity),
                        'current_price_per_kg': rounded(avg_price_per_unit),
                        'unit_price_current': rounded(avg_unit_price),
                        'bulk_option_kg': rounded(avg_quantity * 2),
                        'bulk_price_per_kg': rounded(
                            avg_price_per_unit * BULK_PRICE_SHARE
                        ),
                        'potential_annual_savings': rounded(
                            data['total_price'] * ANNUALISATION * BULK_SAVINGS_SHARE
                        ),
                    }
                )

    return sorted(
        opportunities,
        key=lambda x: x['potential_annual_savings'],
        reverse=True,
    )[:5]


def parse_product_purchases(rows: Any) -> dict[str, Any]:
    """Convert aggregated purchase rows into the product_purchases dict shape."""
    product_purchases: dict[str, Any] = {}
    for row in rows:
        key = row.name
        product_purchases[key] = {
            'brand': row.brand,
            'purchases': sorted(
                [
                    dt.date() if hasattr(dt, 'date') else dt
                    for dt in (row.purchase_dates or [])
                ]
            ),
            'total_quantity': Decimal(row.total_quantity or 0),
            'total_price': Decimal(row.total_price or 0),
            'category': row.category,
            'category_code': row.category_code,
        }
    return product_purchases
