"""Pricing service — compute suggested sale price from cost + target margin.

Pricing model: **gross margin**, food-industry standard.

    sale_price_per_unit = cost_per_unit / (1 - margin/100)
    margin              = (sale - cost) / sale

Stored persistently as ``meta_data['maker']['target_margin_pct']`` on
``ProductTemplate`` (no schema column — per AGENTS.md §4 domain-neutrality).

Per compute is stateless (no DB writes besides the optional margin set).
Caller persists transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.core.money import quantise
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from . import cost_rollup

logger = get_logger(__name__)

META_NAMESPACE = 'maker'
DEFAULT_MARGIN_PCT = Decimal('30')


@dataclass(frozen=True)
class PricingOutcome:
    """A price, and enough context to know whether it means anything.

    A suggested price of zero is a fact when the ingredients are free
    and a void when there are no ingredients; the counts let the caller
    say which one it is looking at.
    """

    total_cost: Decimal
    unit_cost: Decimal
    unit_sale_price: Decimal
    ingredient_count: int
    unrated_ingredient_count: int
    # Which formula the price is about — the same two zero truths the cost
    # breakdown names: no formula at all, or a formula nobody filled.
    recipe_state: str
    recipe_id: UUID | None


def compute_sale_price(
    unit_cost: Decimal,
    target_margin_pct: Decimal,
) -> Decimal:
    """Gross-margin pricing.

    >>> compute_sale_price(Decimal('10'), Decimal('50'))
    Decimal('20.00')
    >>> compute_sale_price(Decimal('10'), Decimal('0'))
    Decimal('10.00')
    """
    if target_margin_pct < 0:
        raise ServiceRejectionError('margin_negative')
    if target_margin_pct >= 100:
        raise ServiceRejectionError('margin_too_high')

    margin = target_margin_pct / Decimal('100')
    if margin == 0:
        return quantise(unit_cost)
    return quantise(unit_cost / (Decimal('1') - margin))


def _read_maker_meta(template_meta: dict[str, Any] | None) -> dict[str, Any]:
    if not template_meta:
        return {}
    nested = template_meta.get(META_NAMESPACE)
    return nested if isinstance(nested, dict) else {}


def _coerce_margin(raw: Any, default: Decimal) -> Decimal:
    """Coerce a stored ``target_margin_pct`` to a safe Decimal in [0, 100)."""
    if raw is None:
        return default
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        logger.warning(
            'Invalid stored margin value %r, using default %s: %s',
            raw,
            default,
            exc,
        )
        return default
    if not value.is_finite() or value < 0 or value >= 100:
        return default
    return value


async def compute_pricing(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    produced_qty: Decimal,
    target_margin_pct: Decimal,
) -> PricingOutcome:
    """Compute unit cost and sale price for a planned production.

    Will raise ``LookupError`` if the template cannot be found in the org, or
    ``ValueError`` if the margin is invalid (>= 100%). Unit cost computation
    may return zero when no rated ingredients exist (per ``cost_rollup``
    contract) — ``ingredient_count`` says whether that zero came from an
    empty formula or from one nobody has priced.
    """
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    if template is None:
        raise NotFoundException('template', get_current_lang())

    rollup = await cost_rollup.compute_cost_rollup(
        db, organization_id, template_id, produced_qty
    )

    if produced_qty <= 0:
        unit_cost = Decimal('0')
    else:
        unit_cost = quantise(rollup.total / produced_qty)

    # The price is computed on the default formula; a product without one
    # and a formula with no lines both answer zero ingredients, and the
    # reader is sent to create the first and to fill the second — so the
    # outcome says which one it is (same vocabulary as the breakdown).
    from . import bom_service

    recipe = await bom_service.find_default_recipe(db, organization_id, template_id)
    recipe_state = (
        'no_recipe'
        if recipe is None
        else ('empty' if rollup.ingredient_count == 0 else 'has_lines')
    )

    return PricingOutcome(
        total_cost=rollup.total,
        unit_cost=unit_cost,
        unit_sale_price=compute_sale_price(unit_cost, target_margin_pct),
        ingredient_count=rollup.ingredient_count,
        unrated_ingredient_count=rollup.unrated_count,
        recipe_state=recipe_state,
        recipe_id=recipe.id if recipe is not None else None,
    )


async def set_default_margin_pct(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    margin_pct: Decimal,
    user_id: UUID | None = None,
) -> Decimal:
    """Persist ``target_margin_pct`` on the template's ``meta_data['maker']``.

    Returns the persisted value (clamped to [0, 100) when invalid).
    """
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    if template is None:
        raise NotFoundException('template', get_current_lang())

    if margin_pct < 0:
        margin_pct = Decimal('0')
    if margin_pct >= 100:
        raise ServiceRejectionError('margin_too_high')

    new_meta = dict(template.meta_data) if template.meta_data else {}  # shallow copy
    maker_meta = dict(_read_maker_meta(new_meta))
    maker_meta['target_margin_pct'] = str(margin_pct)
    new_meta[META_NAMESPACE] = maker_meta

    await core_api.product_templates.update_async(
        db,
        template_id,
        organization_id,
        meta_data=new_meta,
        user_id=user_id,
    )
    return margin_pct
