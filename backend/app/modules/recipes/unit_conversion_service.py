"""Unit conversion management service.

Manages culinary-to-metric conversion reference data.
System defaults (org_id=NULL) are seeded once; org overrides take precedence.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message

from .models import UnitConversion

log = get_logger(__name__)

_CONVERSION_UNIQUE = 'uq_unit_conv_org_ingredient_unit_lang'


def _conversion_exists(ingredient_name: str, source_unit: str) -> ConflictException:
    return ConflictException(
        'UNIT_CONVERSION_ALREADY_EXISTS',
        get_error_message(
            'unit_conversion_already_exists',
            get_current_lang(),
            ingredient=ingredient_name,
            unit=source_unit,
        ),
    )


def _hit_constraint(exc: IntegrityError, name: str) -> bool:
    """Whether an ``IntegrityError`` is the named unique constraint.

    ``constraint_name`` is what asyncpg reports; the string fallback covers
    drivers that only put it in the message. Anything else stays unmapped —
    a refusal must name the rule it refused.
    """
    constraint = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
    return constraint == name or name in str(exc.orig)


# ---------------------------------------------------------------------------
# System seed data
# ---------------------------------------------------------------------------

_SYSTEM_CONVERSIONS_EN: list[tuple[str, str, str, str, str, str]] = [
    ('flour', 'Flour (wheat)', 'cup', '125', 'g', 'dry'),
    ('sugar', 'Sugar (granulated)', 'cup', '200', 'g', 'dry'),
    ('powdered_sugar', 'Powdered sugar', 'cup', '120', 'g', 'dry'),
    ('brown_sugar', 'Brown sugar', 'cup', '220', 'g', 'dry'),
    ('breadcrumbs', 'Breadcrumbs', 'cup', '110', 'g', 'dry'),
    ('oats', 'Oats (rolled)', 'cup', '90', 'g', 'dry'),
    ('rice', 'Rice (raw)', 'cup', '185', 'g', 'dry'),
    ('grated_cheese', 'Grated cheese', 'cup', '100', 'g', 'dry'),
    ('cocoa', 'Cocoa powder', 'cup', '85', 'g', 'dry'),
    ('nuts', 'Nuts (chopped)', 'cup', '140', 'g', 'dry'),
    ('cornstarch', 'Cornstarch', 'cup', '130', 'g', 'dry'),
    ('semolina', 'Semolina', 'cup', '170', 'g', 'dry'),
    ('dried_fruit', 'Dried fruit', 'cup', '150', 'g', 'dry'),
    ('coconut_flakes', 'Coconut flakes', 'cup', '80', 'g', 'dry'),
    ('potato_starch', 'Potato starch', 'cup', '150', 'g', 'dry'),
    ('almond_flour', 'Almond flour', 'cup', '95', 'g', 'dry'),
    ('flour', 'Flour (wheat)', 'tablespoon', '10', 'g', 'dry'),
    ('sugar', 'Sugar (granulated)', 'tablespoon', '13', 'g', 'dry'),
    ('powdered_sugar', 'Powdered sugar', 'tablespoon', '8', 'g', 'dry'),
    ('cocoa', 'Cocoa powder', 'tablespoon', '6', 'g', 'dry'),
    ('cornstarch', 'Cornstarch', 'tablespoon', '8', 'g', 'dry'),
    ('breadcrumbs', 'Breadcrumbs', 'tablespoon', '7', 'g', 'dry'),
    ('rice', 'Rice (raw)', 'tablespoon', '12', 'g', 'dry'),
    ('oats', 'Oats (rolled)', 'tablespoon', '6', 'g', 'dry'),
    ('sugar', 'Sugar (granulated)', 'teaspoon', '4', 'g', 'dry'),
    ('salt', 'Salt', 'teaspoon', '6', 'g', 'dry'),
    ('baking_powder', 'Baking powder', 'teaspoon', '4', 'g', 'dry'),
    ('baking_soda', 'Baking soda', 'teaspoon', '5', 'g', 'dry'),
    ('cinnamon', 'Cinnamon', 'teaspoon', '3', 'g', 'dry'),
    ('pepper', 'Pepper (ground)', 'teaspoon', '2', 'g', 'dry'),
    ('vanilla_sugar', 'Vanilla sugar', 'teaspoon', '4', 'g', 'dry'),
    ('cocoa', 'Cocoa powder', 'teaspoon', '2', 'g', 'dry'),
    ('water', 'Water', 'cup', '250', 'ml', 'liquid'),
    ('milk', 'Milk', 'cup', '250', 'ml', 'liquid'),
    ('cream', 'Cream', 'cup', '250', 'ml', 'liquid'),
    ('oil', 'Oil (cooking)', 'cup', '220', 'ml', 'liquid'),
    ('broth', 'Broth / stock', 'cup', '250', 'ml', 'liquid'),
    ('juice', 'Juice', 'cup', '250', 'ml', 'liquid'),
    ('wine', 'Wine (cooking)', 'cup', '250', 'ml', 'liquid'),
    ('vinegar', 'Vinegar', 'cup', '250', 'ml', 'liquid'),
    ('oil', 'Oil (cooking)', 'tablespoon', '14', 'ml', 'liquid'),
    ('water', 'Water', 'tablespoon', '15', 'ml', 'liquid'),
    ('milk', 'Milk', 'tablespoon', '15', 'ml', 'liquid'),
    ('cream', 'Cream', 'tablespoon', '15', 'ml', 'liquid'),
    ('vinegar', 'Vinegar', 'tablespoon', '15', 'ml', 'liquid'),
    ('soy_sauce', 'Soy sauce', 'tablespoon', '15', 'ml', 'liquid'),
    ('honey', 'Honey', 'tablespoon', '21', 'g', 'liquid'),
    ('lemon_juice', 'Lemon juice', 'tablespoon', '15', 'ml', 'liquid'),
    ('oil', 'Oil (cooking)', 'teaspoon', '5', 'ml', 'liquid'),
    ('vanilla_extract', 'Vanilla extract', 'teaspoon', '5', 'ml', 'liquid'),
    ('lemon_juice', 'Lemon juice', 'teaspoon', '5', 'ml', 'liquid'),
    ('honey', 'Honey', 'teaspoon', '7', 'g', 'liquid'),
    ('butter', 'Butter', 'cup', '225', 'g', 'fat'),
    ('lard', 'Lard / fat', 'cup', '205', 'g', 'fat'),
    ('butter', 'Butter', 'tablespoon', '14', 'g', 'fat'),
    ('lard', 'Lard / fat', 'tablespoon', '13', 'g', 'fat'),
    ('garlic', 'Garlic (1 clove)', 'clove', '3', 'g', 'other'),
    ('salt', 'Salt', 'pinch', '1', 'g', 'other'),
    ('pepper', 'Pepper', 'pinch', '0.5', 'g', 'other'),
    ('yeast_fresh', 'Fresh yeast', 'cube', '42', 'g', 'other'),
    ('gelatin', 'Gelatin', 'sheet', '2', 'g', 'other'),
]

_SYSTEM_CONVERSIONS_PL: list[tuple[str, str, str, str, str, str]] = [
    ('flour', 'Mąka (pszenna)', 'cup', '125', 'g', 'dry'),
    ('sugar', 'Cukier (kryształ)', 'cup', '200', 'g', 'dry'),
    ('powdered_sugar', 'Cukier puder', 'cup', '120', 'g', 'dry'),
    ('brown_sugar', 'Cukier brązowy', 'cup', '220', 'g', 'dry'),
    ('breadcrumbs', 'Bułka tarta', 'cup', '110', 'g', 'dry'),
    ('oats', 'Płatki owsiane', 'cup', '90', 'g', 'dry'),
    ('rice', 'Ryż (surowy)', 'cup', '185', 'g', 'dry'),
    ('grated_cheese', 'Ser tarty', 'cup', '100', 'g', 'dry'),
    ('cocoa', 'Kakao', 'cup', '85', 'g', 'dry'),
    ('nuts', 'Orzechy (posiekane)', 'cup', '140', 'g', 'dry'),
    ('cornstarch', 'Skrobia kukurydziana', 'cup', '130', 'g', 'dry'),
    ('semolina', 'Kasza manna', 'cup', '170', 'g', 'dry'),
    ('dried_fruit', 'Bakalie', 'cup', '150', 'g', 'dry'),
    ('coconut_flakes', 'Wiórki kokosowe', 'cup', '80', 'g', 'dry'),
    ('potato_starch', 'Mąka ziemniaczana', 'cup', '150', 'g', 'dry'),
    ('almond_flour', 'Mąka migdałowa', 'cup', '95', 'g', 'dry'),
    ('flour', 'Mąka (pszenna)', 'tablespoon', '10', 'g', 'dry'),
    ('sugar', 'Cukier (kryształ)', 'tablespoon', '13', 'g', 'dry'),
    ('powdered_sugar', 'Cukier puder', 'tablespoon', '8', 'g', 'dry'),
    ('cocoa', 'Kakao', 'tablespoon', '6', 'g', 'dry'),
    ('cornstarch', 'Skrobia kukurydziana', 'tablespoon', '8', 'g', 'dry'),
    ('breadcrumbs', 'Bułka tarta', 'tablespoon', '7', 'g', 'dry'),
    ('rice', 'Ryż (surowy)', 'tablespoon', '12', 'g', 'dry'),
    ('oats', 'Płatki owsiane', 'tablespoon', '6', 'g', 'dry'),
    ('sugar', 'Cukier (kryształ)', 'teaspoon', '4', 'g', 'dry'),
    ('salt', 'Sól', 'teaspoon', '6', 'g', 'dry'),
    ('baking_powder', 'Proszek do pieczenia', 'teaspoon', '4', 'g', 'dry'),
    ('baking_soda', 'Soda oczyszczona', 'teaspoon', '5', 'g', 'dry'),
    ('cinnamon', 'Cynamon', 'teaspoon', '3', 'g', 'dry'),
    ('pepper', 'Pieprz (mielony)', 'teaspoon', '2', 'g', 'dry'),
    ('vanilla_sugar', 'Cukier waniliowy', 'teaspoon', '4', 'g', 'dry'),
    ('cocoa', 'Kakao', 'teaspoon', '2', 'g', 'dry'),
    ('water', 'Woda', 'cup', '250', 'ml', 'liquid'),
    ('milk', 'Mleko', 'cup', '250', 'ml', 'liquid'),
    ('cream', 'Śmietana', 'cup', '250', 'ml', 'liquid'),
    ('oil', 'Olej (kuchenny)', 'cup', '220', 'ml', 'liquid'),
    ('broth', 'Bulion / wywar', 'cup', '250', 'ml', 'liquid'),
    ('juice', 'Sok', 'cup', '250', 'ml', 'liquid'),
    ('wine', 'Wino (do gotowania)', 'cup', '250', 'ml', 'liquid'),
    ('vinegar', 'Ocet', 'cup', '250', 'ml', 'liquid'),
    ('oil', 'Olej (kuchenny)', 'tablespoon', '14', 'ml', 'liquid'),
    ('water', 'Woda', 'tablespoon', '15', 'ml', 'liquid'),
    ('milk', 'Mleko', 'tablespoon', '15', 'ml', 'liquid'),
    ('cream', 'Śmietana', 'tablespoon', '15', 'ml', 'liquid'),
    ('vinegar', 'Ocet', 'tablespoon', '15', 'ml', 'liquid'),
    ('soy_sauce', 'Sos sojowy', 'tablespoon', '15', 'ml', 'liquid'),
    ('honey', 'Miód', 'tablespoon', '21', 'g', 'liquid'),
    ('lemon_juice', 'Sok z cytryny', 'tablespoon', '15', 'ml', 'liquid'),
    ('oil', 'Olej (kuchenny)', 'teaspoon', '5', 'ml', 'liquid'),
    ('vanilla_extract', 'Ekstrakt waniliowy', 'teaspoon', '5', 'ml', 'liquid'),
    ('lemon_juice', 'Sok z cytryny', 'teaspoon', '5', 'ml', 'liquid'),
    ('honey', 'Miód', 'teaspoon', '7', 'g', 'liquid'),
    ('butter', 'Masło', 'cup', '225', 'g', 'fat'),
    ('lard', 'Smalec', 'cup', '205', 'g', 'fat'),
    ('butter', 'Masło', 'tablespoon', '14', 'g', 'fat'),
    ('lard', 'Smalec', 'tablespoon', '13', 'g', 'fat'),
    ('garlic', 'Czosnek (1 ząbek)', 'clove', '3', 'g', 'other'),
    ('salt', 'Sól', 'pinch', '1', 'g', 'other'),
    ('pepper', 'Pieprz', 'pinch', '0.5', 'g', 'other'),
    ('yeast_fresh', 'Drożdże świeże', 'cube', '42', 'g', 'other'),
    ('gelatin', 'Żelatyna', 'sheet', '2', 'g', 'other'),
]

_SYSTEM_CONVERSIONS_BY_LANG: dict[str, list[tuple[str, str, str, str, str, str]]] = {
    'en': _SYSTEM_CONVERSIONS_EN,
    'pl': _SYSTEM_CONVERSIONS_PL,
}


async def seed_system_conversions(db: AsyncSession) -> int:
    """Insert system-wide conversion defaults if they don't exist yet.

    Seeds all supported languages. Returns the number of rows inserted.
    """
    result = await db.execute(
        select(
            UnitConversion.ingredient_key,
            UnitConversion.source_unit,
            UnitConversion.lang,
        ).where(UnitConversion.organization_id.is_(None))
    )
    existing = {(r.ingredient_key, r.source_unit, r.lang) for r in result.all()}

    added = 0
    for lang, conversions in _SYSTEM_CONVERSIONS_BY_LANG.items():
        for key, name, unit, qty, m_unit, cat in conversions:
            if (key, unit, lang) in existing:
                continue
            db.add(
                UnitConversion(
                    organization_id=None,
                    lang=lang,
                    ingredient_key=key,
                    ingredient_name=name,
                    source_unit=unit,
                    metric_quantity=Decimal(qty),
                    metric_unit=m_unit,
                    category=cat,
                    is_system=True,
                )
            )
            added += 1

    if added:
        await db.flush()
        log.info('Seeded %d system unit conversions', added)
    return added


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def render_conversion_table(conversions: list[UnitConversion]) -> str | None:
    """Render conversions as prompt-friendly text grouped by source unit.

    Returns ``None`` when the list is empty so the caller can fall back to
    a hardcoded table.
    """
    if not conversions:
        return None
    by_unit: dict[str, list[UnitConversion]] = {}
    for conv in conversions:
        by_unit.setdefault(conv.source_unit, []).append(conv)
    lines: list[str] = []
    for unit, entries in sorted(by_unit.items()):
        parts = [f'1 {unit}:']
        for e in entries:
            parts.append(
                f'  {e.ingredient_name} \u2248 {e.metric_quantity} {e.metric_unit}'
            )
        lines.append('\n'.join(parts))
    return '\n'.join(lines)


async def list_conversions(
    db: AsyncSession,
    organization_id: UUID | None = None,
    lang: str = 'en',
) -> list[UnitConversion]:
    """Return all conversions visible to an organization for a given language.

    System defaults + org overrides, with org overrides winning (deduplicated).
    """
    result = await db.execute(
        select(UnitConversion)
        .where(
            UnitConversion.lang == lang,
            or_(
                UnitConversion.organization_id.is_(None),
                UnitConversion.organization_id == organization_id,
            ),
        )
        .order_by(
            UnitConversion.category,
            UnitConversion.ingredient_key,
            UnitConversion.source_unit,
        )
    )
    rows = list(result.scalars().all())

    seen: dict[tuple[str, str], UnitConversion] = {}
    for row in rows:
        k = (row.ingredient_key, row.source_unit)
        if k not in seen:
            seen[k] = row
        elif row.organization_id is not None and seen[k].organization_id is None:
            seen[k] = row
    return list(seen.values())


async def get_conversion(
    db: AsyncSession, conversion_id: UUID, organization_id: UUID | None = None
) -> UnitConversion | None:
    result = await db.execute(
        select(UnitConversion).where(UnitConversion.id == conversion_id)
    )
    conv = result.scalars().first()
    if not conv:
        return None
    if conv.organization_id is not None and conv.organization_id != organization_id:
        return None
    return conv


async def create_conversion(
    db: AsyncSession,
    organization_id: UUID,
    ingredient_key: str,
    ingredient_name: str,
    source_unit: str,
    metric_quantity: Decimal,
    metric_unit: str,
    category: str = 'other',
    lang: str = 'en',
) -> UnitConversion:
    """Create an org-specific conversion (or override a system default).

    A second conversion for the same (ingredient, unit, language) in the same
    organization is refused with 409: the unique index holds one row per key,
    and a caller who wants different numbers edits the row rather than adding
    a twin. The savepoint keeps that refusal from poisoning the request's
    transaction — without it the constraint surfaced as a bare 500.
    """
    ingredient_name = ingredient_name.strip()
    source_unit = source_unit.lower().strip()
    conv = UnitConversion(
        organization_id=organization_id,
        lang=lang,
        ingredient_key=ingredient_key.lower().strip(),
        ingredient_name=ingredient_name,
        source_unit=source_unit,
        metric_quantity=metric_quantity,
        metric_unit=metric_unit.lower().strip(),
        category=category.lower().strip(),
        is_system=False,
    )
    try:
        async with db.begin_nested():
            db.add(conv)
            await db.flush()
    except IntegrityError as exc:
        if _hit_constraint(exc, _CONVERSION_UNIQUE):
            raise _conversion_exists(ingredient_name, source_unit) from exc
        raise
    await db.flush()
    await db.refresh(conv)
    return conv


async def update_conversion(
    db: AsyncSession,
    conversion_id: UUID,
    organization_id: UUID,
    **updates: object,
) -> UnitConversion | None:
    """Update an existing conversion. System defaults can't be edited — create an override instead."""
    conv = await get_conversion(db, conversion_id, organization_id)
    if not conv:
        return None

    if conv.organization_id is None:
        return await create_conversion(
            db,
            organization_id=organization_id,
            ingredient_key=updates.get('ingredient_key', conv.ingredient_key),  # type: ignore[arg-type]
            ingredient_name=updates.get('ingredient_name', conv.ingredient_name),  # type: ignore[arg-type]
            source_unit=updates.get('source_unit', conv.source_unit),  # type: ignore[arg-type]
            metric_quantity=updates.get('metric_quantity', conv.metric_quantity),  # type: ignore[arg-type]
            metric_unit=updates.get('metric_unit', conv.metric_unit),  # type: ignore[arg-type]
            category=updates.get('category', conv.category),  # type: ignore[arg-type]
            lang=conv.lang,
        )

    for key, value in updates.items():
        if hasattr(conv, key) and value is not None:
            setattr(conv, key, value)

    # Read the values the refusal will quote before the savepoint: a failed
    # flush expires the instance, and touching it then asks the poisoned
    # session for a lazy load (PendingRollbackError instead of the 409).
    ingredient_name = conv.ingredient_name
    source_unit = conv.source_unit
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if _hit_constraint(exc, _CONVERSION_UNIQUE):
            raise _conversion_exists(ingredient_name, source_unit) from exc
        raise
    await db.flush()
    await db.refresh(conv)
    return conv


async def delete_conversion(
    db: AsyncSession,
    conversion_id: UUID,
    organization_id: UUID,
) -> bool:
    """Delete an org-specific conversion. System defaults cannot be deleted."""
    conv = await get_conversion(db, conversion_id, organization_id)
    if not conv or conv.organization_id is None:
        return False
    await db.delete(conv)
    await db.flush()
    return True
