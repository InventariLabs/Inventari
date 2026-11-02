"""Which rate goods take: a product's own, or its category's.

The organization keeps its rates in ``tax_rates``; a product or a category
names one of them in ``tax_rate_assignments``. A product's own row wins; a
product without one takes the rate of the category its records are filed
under (``core_api.items.inherited_category_async`` — the category most of
them carry), and with neither the document's default stands. Nothing here
writes to a line: the document workflow asks, and decides.
"""

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from .country_tax_rules import get_country_rule
from .models import TaxRate, TaxRateAssignment


async def product_tax_rates_async(
    db: AsyncSession, org_id: UUID, template_ids: Iterable[UUID | None]
) -> dict[UUID, Decimal]:
    """The rate each product names, by its own row or its category's.

    Products naming nothing are absent from the answer — the caller's
    default applies to them.
    """
    wanted = {tid for tid in template_ids if tid is not None}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(
                TaxRateAssignment.product_template_id,
                TaxRateAssignment.category_id,
                TaxRate.rate,
            )
            .join(TaxRate, TaxRate.id == TaxRateAssignment.tax_rate_id)
            .where(
                TaxRateAssignment.organization_id == org_id,
                or_(
                    TaxRateAssignment.product_template_id.in_(wanted),
                    TaxRateAssignment.category_id.is_not(None),
                ),
            )
        )
    ).all()
    by_product = {p: rate for p, _, rate in rows if p is not None}
    by_category = {c: rate for _, c, rate in rows if c is not None}
    named: dict[UUID, Decimal] = {}
    for tid in wanted:
        if tid in by_product:
            named[tid] = by_product[tid]
        elif by_category:
            category_id = await core_api.items.inherited_category_async(
                db, org_id, template_id=tid
            )
            if category_id in by_category:
                named[tid] = by_category[category_id]
    return named


async def _assignment_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    product_template_id: UUID | None = None,
    category_id: UUID | None = None,
) -> TaxRateAssignment | None:
    stmt = select(TaxRateAssignment).where(TaxRateAssignment.organization_id == org_id)
    if product_template_id is not None:
        stmt = stmt.where(TaxRateAssignment.product_template_id == product_template_id)
    else:
        stmt = stmt.where(TaxRateAssignment.category_id == category_id)
    result: TaxRateAssignment | None = await db.scalar(stmt)
    return result


async def name_rate_async(
    db: AsyncSession,
    org_id: UUID,
    tax_rate_id: UUID | None,
    *,
    product_template_id: UUID | None = None,
    category_id: UUID | None = None,
) -> None:
    """Make one product or one category name *tax_rate_id*; ``None`` clears it.

    The caller has checked that the rate, the product or the category are
    the organization's to name.
    """
    row = await _assignment_async(
        db,
        org_id,
        product_template_id=product_template_id,
        category_id=category_id,
    )
    if tax_rate_id is None:
        if row is not None:
            await db.delete(row)
            await db.flush()
        return
    if row is None:
        row = TaxRateAssignment(
            organization_id=org_id,
            product_template_id=product_template_id,
            category_id=category_id,
        )
        db.add(row)
    row.tax_rate_id = tax_rate_id
    await db.flush()


async def product_assignment_async(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> tuple[UUID | None, UUID | None]:
    """The rate the product names itself, and the one its category names."""
    own = await _assignment_async(db, org_id, product_template_id=template_id)
    category_id = await core_api.items.inherited_category_async(
        db, org_id, template_id=template_id
    )
    by_category = (
        await _assignment_async(db, org_id, category_id=category_id)
        if category_id is not None
        else None
    )
    return (
        own.tax_rate_id if own else None,
        by_category.tax_rate_id if by_category else None,
    )


async def list_category_assignments_async(
    db: AsyncSession, org_id: UUID
) -> list[tuple[UUID, UUID]]:
    """Every category naming a rate, as ``(category_id, tax_rate_id)``."""
    rows = await db.execute(
        select(TaxRateAssignment.category_id, TaxRateAssignment.tax_rate_id)
        .where(
            TaxRateAssignment.organization_id == org_id,
            TaxRateAssignment.category_id.is_not(None),
        )
        .order_by(TaxRateAssignment.category_id)
    )
    return [(c, r) for c, r in rows.all() if c is not None]


def country_rate_offer(country: str | None) -> list[tuple[str, Decimal, bool]]:
    """The rates a country's law knows, as ``(name, rate, is_standard)``.

    Standard first, then the reduced ones in the order the rule lists them.
    A country without a rule offers nothing.
    """
    rule = get_country_rule(country)
    if rule is None:
        return []
    rates = [(rule.default_tax_rate, True)] + [
        (rate, False) for rate in rule.reduced_tax_rates
    ]
    return [
        (f'{rule.tax_name} {rate.normalize():f}%', rate, is_standard)
        for rate, is_standard in rates
    ]
