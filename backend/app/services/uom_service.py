"""Read-only service for Units of Measure."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import NamedTuple, Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ServiceRejectionError
from app.core.money import quantise
from app.i18n.service import get_unit_label, stated_quantity
from app.models.uom import Uom
from app.schemas.validators import QUANTITY_STEP


class UomLike(Protocol):
    """Structural UoM contract for conversion — satisfied by both the
    ``Uom`` ORM model and the CoreAPI ``UomDTO``."""

    id: UUID
    category_id: UUID
    factor: Decimal
    #: The smallest step the unit is counted in. Read through
    #: :func:`quantity_step` rather than directly — a unit may name a step
    #: finer than the quantity columns can keep.
    rounding: Decimal


def convert_quantity(
    qty: Decimal,
    source: UomLike | None,
    target: UomLike | None,
) -> tuple[Decimal, bool]:
    """Convert *qty* from *source* UoM to *target* UoM.

    Uses the ``factor`` column (relative to the category's reference UoM).

    Returns ``(converted_qty, convertible)``.  When conversion is impossible
    (either UoM is None, different categories, or target factor is zero),
    returns ``(qty, False)`` — caller should treat the quantity as
    non-convertible and report in the original unit.

    Supported dimensions: mass (g/kg), volume (ml/l), length (m/cm), units.
    Cross-dimension conversion (e.g. cup↔kg requiring density) is NOT
    supported and returns ``convertible=False``.

    Bulk packaging (pack/can/bottle/box/bag) is not a share of the piece's
    dimension either: each of those units seeds into its own single-unit
    category, so pack↔pcs refuses — the packaging-to-contents ratio belongs
    to the product, not the unit table.
    """
    if source is None or target is None:
        return qty, False
    if source.id == target.id:
        return qty, True
    if source.category_id != target.category_id:
        return qty, False
    # Both sides are exact numbers now, so no ``Decimal(str(...))`` rescue
    # is needed on the way in — and none is possible on the way out either,
    # which is why the column stopped being a float.
    if target.factor == 0:
        return qty, False
    return qty * source.factor / target.factor, True


def quantity_step(uom: UomLike | None) -> Decimal:
    """The step a quantity stated in *uom* is counted in.

    ``Uom.rounding`` is the unit's own answer — 1 for a piece, 0.5 for goods
    sold in halves, 0.001 for a gram — and it is the answer consumers are
    meant to use. It is floored at the quantity columns' own scale because a
    finer step is rounded away by the database anyway, silently; a unit that
    names no step falls back to that same scale, which is what every consumer
    assumed before it thought to ask.

    A ``rounding`` of zero or less reads as *no step named*, not as *whole
    numbers only* — it lands on the same floor, so such a unit would accept
    a fraction. No unit in the catalogue carries it and the API has no way
    to create one; if one ever can be, that is the line to revisit.
    """
    raw = getattr(uom, 'rounding', None) if uom is not None else None
    if raw is None:
        return QUANTITY_STEP
    step = Decimal(str(raw)).normalize()
    if step == step.to_integral_value():
        step = step.quantize(Decimal('1'))
    return step if step > QUANTITY_STEP else QUANTITY_STEP


def _on_step(qty: Decimal, step: Decimal, rounding: str) -> Decimal:
    if step <= 0:
        return qty
    return (qty / step).quantize(Decimal('1'), rounding=rounding) * step


def quantize_to_uom(qty: Decimal, uom: UomLike | None) -> Decimal:
    """*qty* on the nearest step of *uom* — the rounding a measurement takes.

    What was scanned, what left the shelf, what a recipe originally said:
    these are readings, and the nearest step is the honest one, the same rule
    :func:`app.schemas.validators.quantize_quantity` applies at the door.
    """
    return _on_step(qty, quantity_step(uom), ROUND_HALF_UP)


def round_up_to_uom(qty: Decimal, uom: UomLike | None) -> Decimal:
    """*qty* on the next step of *uom* at or above it — the rounding a
    requirement takes.

    A requirement put on the nearest step can land on zero: a third of an egg
    would tell the shopping list to buy none, and a whole-unit ingredient
    would tell picking that nothing is owed. Needing part of a step is
    needing the step.
    """
    return _on_step(qty, quantity_step(uom), ROUND_CEILING)


class CanonicalMeasure(NamedTuple):
    """A quantity restated in its category's reference unit."""

    amount: Decimal
    #: The reference unit's symbol — ``g`` for the weight family,
    #: ``ml`` for volume — so the caller knows what was answered.
    symbol: str


async def to_canonical_measure_async(
    db: AsyncSession,
    qty: Decimal,
    uom: UomLike | None,
) -> CanonicalMeasure | None:
    """Express *qty* in the reference unit of *uom*'s own category.

    The reference unit is the canonical measure of the family — grams for
    Weight, millilitres for Volume — so this is the one doorway for "how
    many grams is this": ask it, read the symbol, and refuse when it says
    the measures don't meet. Nutrition used to carry private tables whose
    ounce was 28.35 against the catalogue's 28.3495; everything now goes
    through :func:`convert_quantity` and the seeded factors.

    Returns ``None`` when there is no unit, the category has no reference
    row, or the conversion refuses — never a silently unchanged quantity.
    """
    if uom is None:
        return None
    result = await db.scalars(
        select(Uom).where(
            Uom.category_id == uom.category_id,
            Uom.is_reference.is_(True),
        )
    )
    reference = result.first()
    if reference is None:
        return None
    converted, ok = convert_quantity(qty, uom, reference)
    if not ok:
        return None
    return CanonicalMeasure(converted, reference.symbol)


async def get_uom_by_symbol_async(
    db: AsyncSession, symbol: str, organization_id: UUID | None = None
) -> Uom | None:
    """Async: return the Uom row whose ``symbol`` matches exactly, or None."""
    from app.models.uom import Uom

    query = select(Uom).where(Uom.symbol == symbol)
    if organization_id is not None:
        query = query.where(
            or_(Uom.organization_id == organization_id, Uom.organization_id.is_(None))
        ).order_by(Uom.organization_id.is_(None))
    result = await db.scalars(query)
    return result.first()


async def get_uom_async(
    db: AsyncSession, uom_id: UUID, organization_id: UUID | None = None
) -> Uom | None:
    """Async: return the Uom row for *uom_id*, or None.

    With *organization_id* the row must be one the organization may see:
    its own unit or the system catalogue (``organization_id IS NULL``).
    Passing ``None`` is the deliberate unscoped read internal conversions
    make when both ids already came from org-scoped lookups; a caller that
    holds a tenant passes it.
    """
    from app.models.uom import Uom

    query = select(Uom).where(Uom.id == uom_id)
    if organization_id is not None:
        query = query.where(
            or_(Uom.organization_id == organization_id, Uom.organization_id.is_(None))
        )
    result = await db.scalars(query)
    return result.first()


async def existing_uom_ids_async(
    db: AsyncSession, uom_ids: set[UUID], organization_id: UUID
) -> set[UUID]:
    """Async: return the subset of *uom_ids* that have a row in the uoms table.

    One query for the whole set — the batch counterpart of
    :func:`get_uom_async`, for callers that validate a handful of foreign
    keys and would otherwise pay one round-trip per id.  Scoped to the
    organization's own units plus the system catalogue (``organization_id
    IS NULL``), same visibility as :func:`list_uoms_for_org_async`.
    """
    from app.models.uom import Uom

    result = await db.scalars(
        select(Uom.id).where(
            Uom.id.in_(uom_ids),
            (Uom.organization_id == organization_id) | (Uom.organization_id.is_(None)),
        )
    )
    return set(result.all())


async def list_uoms_for_org_async(db: AsyncSession, organization_id: UUID) -> list[Uom]:
    """Return all Uom rows visible to *organization_id* using an AsyncSession."""
    from app.models.uom import Uom

    result = await db.scalars(
        select(Uom).where(
            or_(Uom.organization_id == organization_id, Uom.organization_id.is_(None))
        )
    )
    return list(result.all())


async def list_uom_categories_for_org_async(
    db: AsyncSession, organization_id: UUID
) -> list:
    """Return all UomCategory rows visible to *organization_id* with eager-loaded uoms."""
    from app.models.uom import UomCategory

    result = await db.scalars(
        select(UomCategory)
        .options(selectinload(UomCategory.uoms))
        .where(
            or_(
                UomCategory.organization_id == organization_id,
                UomCategory.organization_id.is_(None),
            )
        )
    )
    return list(result.all())


def _kept_decimal_places(step: Decimal) -> int:
    """How many decimal places *step* really keeps — 2 for a centimetre.

    The column is ``numeric(12, 6)``, so a unit seeded as 0.01 reads back as
    ``Decimal('0.010000')``: six places by its scale, two by what it keeps.
    The refusal fires for a quantity finer than the step, so the second is
    the count a reader may be told; the first said 6 for every measured unit.
    """
    return abs(int(step.normalize().as_tuple().exponent))


async def validate_quantity_precision_async(
    db: AsyncSession,
    uom_id: UUID,
    quantity: Decimal,
    organization_id: UUID | None = None,
) -> None:
    """Async: refuse a *quantity* the given UoM cannot hold.

    Raises ``ServiceRejectionError`` — the refusal reaches a reader (a toast
    on the scan screen, the 400 body, an email), so it speaks the request's
    language and names the unit by its label, not by its symbol. For a
    negative quantity this gate is the last line, rarely the first: the
    request schemas carry ``ge=0`` and answer before the service is reached.
    The branch exists for callers that arrive without a schema.

    With *organization_id* the unit must be one the organization may see —
    its own or the system catalogue. A unit it cannot see is refused like an
    unknown one: the caller named a unit that is not theirs, and answering
    "fine" would apply a stranger's step (or none at all) to their stock.
    Without it the lookup is unscoped, which is the internal path whose ids
    already came from org-scoped rows.
    """
    if uom_id is None:
        return
    # Reject negative quantities outright — they are never valid for stock.
    if quantity < 0:
        raise ServiceRejectionError('uom_quantity_non_negative')
    query = select(Uom).where(Uom.id == uom_id)
    if organization_id is not None:
        query = query.where(
            or_(Uom.organization_id == organization_id, Uom.organization_id.is_(None))
        )
    result = await db.scalars(query)
    uom = result.first()
    if uom is None:
        if organization_id is not None:
            raise ServiceRejectionError('uom_not_found')
        return
    rounding = Decimal(str(uom.rounding))
    if rounding >= Decimal('1'):
        if quantity != quantity.to_integral_value():
            raise ServiceRejectionError(
                'uom_quantity_requires_whole_number',
                unit=get_unit_label(uom.symbol),
                quantity=stated_quantity(quantity),
            )
    else:
        remainder = quantity % rounding
        tolerance = rounding / Decimal('1000')
        if remainder > tolerance and (rounding - remainder) > tolerance:
            raise ServiceRejectionError(
                'uom_quantity_too_many_decimal_places',
                unit=get_unit_label(uom.symbol),
                places=_kept_decimal_places(rounding),
                quantity=stated_quantity(quantity),
            )


#: Decimals a stock quantity is kept to — the scale of every quantity column
#: in the schema (``numeric(12,3)``).
STOCK_PLACES = 3


async def to_stock_uom_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID | None,
    quantity: Decimal,
    uom_id: UUID | None,
) -> Decimal:
    """Express *quantity*, stated in *uom_id*, in the product's stock unit.

    A quant and a movement carry a number and no unit, so whose unit it is
    depends on whichever write got there last — receive 500 g of something
    kept in kilograms and the shelf gains 500 kg, silently, in the ledger,
    the valuation and every report. The rule every WMS keeps instead is that
    a product names one stock unit and every entry is converted into it.

    Refuses rather than guesses: pieces do not become kilograms, and a
    keyed refusal in the reader's language naming both units is a better
    answer than a number.

    Passes the quantity through untouched when either side names no unit.
    Products that predate units are the majority of some catalogues, and a
    rule that locked them out would close the door on the data it exists to
    protect.
    """
    from app.models.product_template import ProductTemplate

    if uom_id is None or product_template_id is None:
        return quantity
    # Org-scoped exactly like the valuation lookups: a global template
    # (``organization_id IS NULL``) stays usable, anything else has to belong
    # to the caller. Otherwise a passed-in id decides which unit this
    # organization's stock is converted into.
    # By identity, so a posting that has the card in hand asks nobody.
    template = await db.get(ProductTemplate, product_template_id)
    template_uom_id = (
        template.uom_id
        if template is not None and template.organization_id in (organization_id, None)
        else None
    )
    if template_uom_id is None or template_uom_id == uom_id:
        return quantity

    source = await get_uom_async(db, uom_id)
    target = await get_uom_async(db, template_uom_id)
    converted, ok = convert_quantity(quantity, source, target)
    if not ok:
        raise ServiceRejectionError(
            'uom_conversion_unavailable',
            unit=get_unit_label(source.symbol if source else str(uom_id)),
            stock_unit=get_unit_label(
                target.symbol if target else str(template_uom_id)
            ),
        )
    # Rounded here, where the conversion happens, to the three decimals every
    # stock column holds. The quotient used to be handed over at full
    # precision and rounded on the way into the column — the right answer,
    # arrived at by nobody's decision, and a number the code that computed it
    # could not recognise afterwards. Half away from zero, like every other
    # rounding in this codebase.
    return quantise(converted, STOCK_PLACES)
