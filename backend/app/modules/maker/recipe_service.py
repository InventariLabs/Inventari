"""Recipe service — CRUD, catalog and module settings.

Handles all recipe-level operations that go beyond the legacy BOM-line API
(``bom_service``). The catalog query enriches recipes with last-unit-cost,
stock and production history without N+1 queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.db_utils import acquire_advisory_lock, escape_ilike, paginate_async
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.money import quantise, quantise_or_none
from app.core.public_api import core_api

from . import bom_service
from ._schemas_recipes import (
    BoMLineCreateForRecipe,
    BoMLineUpdate,
    RecipeCostLineCreate,
    RecipeCostLineUpdate,
    RecipeCreate,
    RecipeFromCulinaryCreate,
    RecipeUpdate,
)
from .models import (
    BoMLine,
    MakerModuleSettings,
    MakerRecipe,
    MakerRecipeCostLine,
    ProductionOrder,
    ProductionOrderLine,
)

# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------
#
# A production recipe is not a note somebody keeps: it decides what a run
# takes off the shelf and at what cost. ``complete_order`` expands it *live*
# (``production_service._explode_planned_consumption`` → ``bom_service``) and
# writes ``ProductionOrderLine`` rows only afterwards, as a record of what
# happened — so a line edited while an order is open changes what that order
# will consume, and nothing else records that the formula moved. Every write
# below therefore leaves one row naming the recipe and, where a value moved,
# both sides of the move.


def _recipe_shape(recipe: MakerRecipe) -> dict[str, Any]:
    """The fields a reader would want back if a change turned out wrong."""
    return {
        'name': recipe.name,
        'batch_yield_qty': quantise_or_none(recipe.batch_yield_qty, 4),
        'reference_price': quantise_or_none(recipe.reference_price, 2),
        'is_default': recipe.is_default,
        'process_steps': recipe.process_steps,
    }


def _line_shape(line: BoMLine, uom_symbol: str | None = None) -> dict[str, Any]:
    """The fields of an ingredient line that change what a run consumes.

    The unit travels as its symbol, not as its id: a journal entry saying
    ``uom_id: null → 38690ddd-…`` records a change nobody can read, and the
    row is opened months later precisely to find out what the line used to
    say. The id is resolved at write time because the row is immutable
    afterwards — resolving it on the way out would mean a rename rewrote
    history.
    """
    return {
        'qty_per_batch': quantise_or_none(line.qty_per_batch, 4),
        'uom': uom_symbol,
        'yield_loss_pct': quantise_or_none(line.yield_loss_pct, 2),
        'notes': line.notes,
    }


async def _uom_symbol(
    db: AsyncSession, uom_id: UUID | None, organization_id: UUID
) -> str | None:
    """The unit's symbol, or None when the line names no unit."""
    if uom_id is None:
        return None
    uom = await core_api.uoms.get_async(db, uom_id, organization_id)
    return uom.symbol if uom is not None else None


def _cost_line_shape(line: MakerRecipeCostLine) -> dict[str, Any]:
    """The fields of a fixed-cost line that change what a batch costs."""
    return {
        'kind': line.kind,
        'label': line.label,
        'amount': quantise_or_none(line.amount, 2),
    }


def _changed_fields(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Only what moved, as ``before``/``after`` — the journal's own shape.

    An entry listing every field says nothing about which one the author
    touched, and the journal is read to answer exactly that. The two sides
    are named the way every other service names them, because the audit
    screen renders that shape as "Field: old → new" and renders anything
    else by printing the JSON — which is what this service's own
    ``{'changed': {...}}`` used to get.

    Returns an empty dict when nothing moved, so the caller can keep asking
    ``if changed:``.
    """
    moved = [key for key in before if before[key] != after[key]]
    if not moved:
        return {}
    return {
        'before': {key: before[key] for key in moved},
        'after': {key: after[key] for key in moved},
    }


async def _line_count(db: AsyncSession, organization_id: UUID, recipe_id: UUID) -> int:
    """How many ingredient lines go away with a recipe."""
    return (
        await db.scalar(
            select(func.count(BoMLine.id)).where(
                BoMLine.organization_id == organization_id,
                BoMLine.recipe_id == recipe_id,
            )
        )
    ) or 0


async def log_recipe_change(
    db: AsyncSession,
    organization_id: UUID,
    user: UserContextDTO | None,
    recipe: MakerRecipe,
    action: AuditAction,
    detail: dict[str, Any] | None = None,
) -> None:
    """One journal row about *recipe*, always carrying its name."""
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user.id if user is not None else None,
        action=action,
        target_type=AuditTargetType.MAKER_RECIPE,
        target_id=recipe.id,
        snapshot={'name': recipe.name, **(detail or {})},
    )


async def ingredient_name(
    db: AsyncSession, organization_id: UUID, template_id: UUID
) -> str | None:
    """What an ingredient is called, so the entry reads without a join."""
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    return template.name if template else None


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------


async def get_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
) -> MakerRecipe | None:
    result = await db.execute(
        select(MakerRecipe).where(
            MakerRecipe.organization_id == organization_id,
            MakerRecipe.id == recipe_id,
        )
    )
    return result.scalar_one_or_none()


async def create_recipe(
    db: AsyncSession,
    organization_id: UUID,
    data: RecipeCreate,
    user: UserContextDTO | None = None,
) -> MakerRecipe:
    """Create a new recipe. The first recipe for a template is auto-default."""
    await acquire_advisory_lock(
        db, bom_service.first_default_lock_key(organization_id, data.output_template_id)
    )
    existing_count = await db.scalar(
        select(func.count(MakerRecipe.id)).where(
            MakerRecipe.organization_id == organization_id,
            MakerRecipe.output_template_id == data.output_template_id,
        )
    )
    is_first = (existing_count or 0) == 0
    is_default = data.is_default if not is_first else True

    recipe = MakerRecipe(
        organization_id=organization_id,
        output_template_id=data.output_template_id,
        name=data.name,
        batch_yield_qty=data.batch_yield_qty,
        batch_yield_uom_id=data.batch_yield_uom_id,
        process_steps=data.process_steps,
        reference_price=data.reference_price,
        is_default=is_default,
        source_recipe_id=data.source_recipe_id,
        # Any creation stamped with a culinary source is a frozen
        # snapshot — record when it was taken (the source itself is a
        # plain UUID, no FK). Constructor kwarg keeps vulture quiet (the
        # column is consumed via dynamic ORM serialization).
        source_snapshot_at=(
            datetime.now(tz=UTC) if data.source_recipe_id is not None else None
        ),
    )
    db.add(recipe)
    await db.flush()
    await log_recipe_change(
        db,
        organization_id,
        user,
        recipe,
        AuditAction.CREATE,
        {
            'output': await ingredient_name(
                db, organization_id, data.output_template_id
            ),
            'batch_yield_qty': quantise_or_none(data.batch_yield_qty, 4),
            'is_default': is_default,
        },
    )
    return recipe


async def create_recipe_from_culinary(
    db: AsyncSession,
    organization_id: UUID,
    data: RecipeFromCulinaryCreate,
    user: UserContextDTO | None = None,
) -> tuple[MakerRecipe, bool]:
    """Create a maker recipe as a one-way snapshot of a culinary recipe.

    Flow:
    1. Idempotency — an existing recipe for the same
       (output_template_id, source_recipe_id) pair is returned as-is, so
       repeated "cook for stock" clicks never duplicate snapshots.
    2. The culinary recipe is read through ``recipes_api`` (public API of
       the recipes module — no internal imports; graceful 404 when the
       recipe is missing or the module is disabled).
    3. A new ``MakerRecipe`` is stamped with ``source_recipe_id`` +
       ``source_snapshot_at`` (plain UUID, no FK — module boundaries).
    4. BOM lines are derived from the culinary ingredients that are linked
       to product templates (``template_id``). Free-text ingredients are
       skipped — they have no stock to consume. The snapshot is frozen:
       later edits of the culinary recipe never propagate.

    Returns the recipe and whether this call is what created it. The
    caller is usually mid-way through a two-step bridge — snapshot, then
    production order — and if the second step is abandoned it has to know
    whether the snapshot is its own litter or a record that was already
    there.

    Raises ``LookupError`` when the culinary recipe is not found in the org.
    """
    # Lazy import — keeps the maker module loadable and the dependency
    # direction explicit (maker → recipes public API, never the reverse).
    from app.modules.recipes.recipes_api import recipes_api

    # Same advisory lock as create_recipe — serializes the idempotency
    # select + insert per (org, template) pair.
    await acquire_advisory_lock(
        db, bom_service.first_default_lock_key(organization_id, data.output_template_id)
    )
    existing = await db.scalar(
        select(MakerRecipe.id).where(
            MakerRecipe.organization_id == organization_id,
            MakerRecipe.output_template_id == data.output_template_id,
            MakerRecipe.source_recipe_id == data.source_recipe_id,
        )
    )
    if existing is not None:
        recipe = await get_recipe(db, organization_id, existing)
        assert recipe is not None  # fetched by id from the same org
        return recipe, False

    snapshot = await recipes_api.get_recipe_snapshot_async(
        db, organization_id, data.source_recipe_id
    )
    if snapshot is None:
        raise EntityNotFoundError('maker_recipe', 'Source recipe not found')

    # Only the first snapshot for this output becomes default — a second
    # culinary recipe bridged to the same product would otherwise hit the
    # partial unique index (one default per template). The advisory lock
    # above makes this check race-safe.
    has_default = (
        await db.scalar(
            select(MakerRecipe.id).where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.output_template_id == data.output_template_id,
                MakerRecipe.is_default.is_(True),
            )
        )
    ) is not None

    recipe = MakerRecipe(
        organization_id=organization_id,
        output_template_id=data.output_template_id,
        name=data.name or snapshot.name,
        batch_yield_qty=data.batch_yield_qty or Decimal(snapshot.servings),
        batch_yield_uom_id=data.batch_yield_uom_id,
        is_default=not has_default,
        source_recipe_id=snapshot.id,
        source_snapshot_at=datetime.now(tz=UTC),
    )
    db.add(recipe)
    await db.flush()

    for ing in snapshot.ingredients:
        if ing.template_id is None:
            continue
        # `unit` is a legacy 8-char symbol column; uom_id carries the real
        # structural unit. Symbol length is bounded defensively (UoM symbols
        # are user-editable).
        unit = (ing.uom_symbol or 'szt')[:8]
        db.add(
            BoMLine(
                organization_id=organization_id,
                recipe_id=recipe.id,
                parent_template_id=data.output_template_id,
                child_template_id=ing.template_id,
                qty_per_batch=ing.quantity,
                uom_id=ing.uom_id,
                unit=unit,
                yield_loss_pct=Decimal('0'),
            )
        )
    await db.flush()
    # Only the call that created it logs. The idempotent early return above
    # is not an act — a second "cook for stock" click changed nothing.
    await log_recipe_change(
        db,
        organization_id,
        user,
        recipe,
        AuditAction.CREATE,
        {
            'output': await ingredient_name(
                db, organization_id, data.output_template_id
            ),
            'copied_from_culinary_recipe': snapshot.name,
            'lines': await _line_count(db, organization_id, recipe.id),
        },
    )
    return recipe, True


async def update_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    data: RecipeUpdate,
    user: UserContextDTO | None = None,
) -> MakerRecipe:
    recipe = await get_recipe(db, organization_id, recipe_id)
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    # Read before the assignments below, so the entry can carry both sides.
    before = _recipe_shape(recipe)

    if data.name is not None:
        recipe.name = data.name
    if data.batch_yield_qty is not None:
        recipe.batch_yield_qty = data.batch_yield_qty
    if data.batch_yield_uom_id is not None:
        recipe.batch_yield_uom_id = data.batch_yield_uom_id
    if data.process_steps is not None:
        recipe.process_steps = data.process_steps
    if data.reference_price is not None:
        recipe.reference_price = data.reference_price
    if data.is_default is True and not recipe.is_default:
        # The same lock the creating paths hold: this path breaks the
        # invariant (one default per template) the index polices, so two
        # clear-then-set turns must not interleave — without the lock two
        # parallel flips end with two defaults (the index refuses one with a
        # raw IntegrityError) or, on the other timing, with none.
        await acquire_advisory_lock(
            db,
            bom_service.first_default_lock_key(
                organization_id, recipe.output_template_id
            ),
        )
        # The partial unique index prevents two defaults, so the existing one
        # has to go first — as an immediate UPDATE, not the unit of work: the
        # ORM flushes both changes in one batch ordered by primary key, and
        # uuid keys do not order the clear before the set, so an ORM-side
        # clear could stand beside the new default for one statement and the
        # index would refuse the batch (the race the concurrent test pins).
        await db.execute(
            update(MakerRecipe)
            .where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.output_template_id == recipe.output_template_id,
                MakerRecipe.is_default.is_(True),
                MakerRecipe.id != recipe_id,
            )
            .values(is_default=False)
        )
        recipe.is_default = True

    await db.flush()
    changed = _changed_fields(before, _recipe_shape(recipe))
    if changed:
        await log_recipe_change(
            db, organization_id, user, recipe, AuditAction.UPDATE, changed
        )
    return recipe


async def delete_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    user: UserContextDTO | None = None,
) -> None:
    from .exceptions import RecipeInUseError

    # The row is locked from the first read: the answer to "is it there" and
    # the delete below then see the same row, and two deletes of the default
    # cannot both promote a successor.
    recipe = (
        await db.execute(
            select(MakerRecipe)
            .where(
                MakerRecipe.organization_id == organization_id,
                MakerRecipe.id == recipe_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    # Production orders keep an FK to the recipe — deleting would violate it
    # with a raw IntegrityError (500). Fail fast with a business conflict.
    referenced_order = await db.scalar(
        select(ProductionOrder.id)
        .where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.recipe_id == recipe_id,
        )
        .limit(1)
    )
    if referenced_order is not None:
        raise RecipeInUseError(f'Recipe {recipe_id} is referenced by production orders')

    # Logged before the delete: afterwards the name is gone, and the name is
    # the only part of the row a reader can act on.
    await log_recipe_change(
        db,
        organization_id,
        user,
        recipe,
        AuditAction.HARD_DELETE,
        {
            'output': await ingredient_name(
                db, organization_id, recipe.output_template_id
            ),
            'lines_removed': await _line_count(db, organization_id, recipe_id),
        },
    )
    template_id = recipe.output_template_id
    was_default = recipe.is_default
    await db.delete(recipe)
    await db.flush()

    if was_default:
        # A template with at least one recipe always has exactly one default:
        # the oldest remaining recipe takes over.
        next_default = (
            await db.execute(
                select(MakerRecipe)
                .where(
                    MakerRecipe.organization_id == organization_id,
                    MakerRecipe.output_template_id == template_id,
                )
                .order_by(MakerRecipe.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if next_default is not None:
            next_default.is_default = True
            await db.flush()


# ---------------------------------------------------------------------------
# BOM lines (per recipe)
# ---------------------------------------------------------------------------


async def _get_line_of_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    line_id: UUID,
) -> BoMLine:
    """Fetch a line by (id, recipe, org) or raise 404.

    Scoping on ``recipe_id`` too — a line id alone would let a caller edit a
    sibling formula's line by naming the wrong recipe in the path.
    """
    result = await db.execute(
        select(BoMLine).where(
            BoMLine.id == line_id,
            BoMLine.recipe_id == recipe_id,
            BoMLine.organization_id == organization_id,
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        # Logs and non-decorated callers only: ``map_service_errors`` builds
        # the 404 from the resource slug, so this detail never reaches a
        # response body — but it keeps the glossary spelling anyway.
        raise EntityNotFoundError('bom_line', f'BOM line {line_id} not found')
    return line


async def _stock_unit_from_items_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
) -> UUID | None:
    """The unit this product's shelves actually hold, when the catalogue is silent.

    The piece backfill (archived ``uompcs01``) gave every item row a unit, so a
    unitless template whose items exist is not a product predating units —
    its shelves answer "pieces" whether the catalogue row does or not. The
    items have to agree; a product held in several units has no single stock
    unit to compare the line against, and the guard stays out of the way.
    One column over the whole set: a paginated sample would let a hundred
    newest rows outvote an older one.
    """
    units = {
        uom_id
        for uom_id in await core_api.items.distinct_uom_ids_for_template_async(
            db, organization_id, template_id=template_id
        )
        if uom_id is not None
    }
    return units.pop() if len(units) == 1 else None


async def _refuse_unconvertible_unit(
    db: AsyncSession,
    organization_id: UUID,
    child_template_id: UUID,
    line_uom_id: UUID | None,
) -> None:
    """Refuse a line written in a unit the ingredient's stock cannot be read in.

    The line's unit and the product's stock unit have to meet somewhere, or the
    quantity on the line means nothing the ledger can act on. This was checked
    nowhere: cycles and self-reference were, units were not, so "7 pieces of
    flour" against stock kept in kilograms could be saved and then costed and
    consumed as a number with no unit attached to it.

    The stock unit comes from the template, falling back to the unit the
    template's items actually carry — the whole set, not a page of it: a
    hundred newest rows must not outvote an older one and flip the verdict
    both ways. The silence this leaves is narrow on purpose: with the piece
    backfill in place, a unitless template that has no items at all is the
    only state where nothing knows the unit — a record that genuinely
    predates the units world. A unitless template whose shelves hold pieces
    gets the refusal, because there the silence protected a live hole, not
    history. And the pieces those shelves hold are not merely the default's
    guess: the backfill wrote real rows, so the shelf genuinely holds
    pieces now.
    """
    if line_uom_id is None:
        return
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, [child_template_id]
    )
    template = templates.get(child_template_id)
    stock_uom_id = template.uom_id if template else None
    if stock_uom_id is None:
        stock_uom_id = await _stock_unit_from_items_async(
            db, organization_id, child_template_id
        )
    if stock_uom_id is None or stock_uom_id == line_uom_id:
        return

    uoms = {
        uom.id: uom
        for uom in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    line_uom = uoms.get(line_uom_id)
    stock_uom = uoms.get(stock_uom_id)
    _, convertible = core_api.uoms.convert_quantity(Decimal('1'), line_uom, stock_uom)
    if convertible:
        return

    raise ServiceRejectionError(
        'bom_line_unit_not_convertible',
        line_unit=line_uom.symbol if line_uom else '?',
        stock_unit=stock_uom.symbol if stock_uom else '?',
    )


async def add_bom_line(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    data: BoMLineCreateForRecipe,
    user: UserContextDTO | None = None,
) -> BoMLine:
    """Add an ingredient line to the recipe named in the path.

    The legacy ``bom_service.add_line`` adapter resolves a parent template to
    that template's *default* recipe, so it cannot address a second formula
    for the same product. This path takes the recipe directly and derives the
    parent from it, keeping invariant #9 true by construction.
    """
    from .exceptions import DuplicateBomLineError

    recipe = await get_recipe(db, organization_id, recipe_id)
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    if recipe.output_template_id == data.child_template_id:
        # The ingredient picker offers the output product too, so a reader
        # can genuinely click this refusal into existence — the keyed
        # rejection carries the glossary's spelling of the module noun
        # (BOM, per docs/MODULE_NAMES.md) into every language.
        raise ServiceRejectionError('bom_line_self_reference')

    # The ingredient's template is a payload foreign key, the one class the
    # tenancy linter cannot see: an unchecked id wrote a line pointing into
    # another organization's catalogue. The recipes module validates the
    # identical field; the sibling FKs here (self-reference, cycle, unit
    # convertibility) all read org-scoped and missed it.
    ingredient_template = await core_api.product_templates.get_async(
        db, organization_id, data.child_template_id
    )
    if ingredient_template is None:
        raise EntityNotFoundError(
            'product_template',
            f'Template {data.child_template_id} not found',
        )

    await bom_service.ensure_no_cycle(
        db, organization_id, recipe.output_template_id, data.child_template_id
    )

    await _refuse_unconvertible_unit(
        db, organization_id, data.child_template_id, data.uom_id
    )

    line = BoMLine(
        organization_id=organization_id,
        recipe_id=recipe.id,
        parent_template_id=recipe.output_template_id,
        child_template_id=data.child_template_id,
        qty_per_batch=data.qty_per_batch,
        uom_id=data.uom_id,
        unit=data.unit,
        yield_loss_pct=data.yield_loss_pct,
        notes=data.notes,
    )
    db.add(line)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise DuplicateBomLineError(
            f'Recipe {recipe_id} already lists ingredient {data.child_template_id}'
        ) from exc
    await log_recipe_change(
        db,
        organization_id,
        user,
        recipe,
        AuditAction.UPDATE,
        {
            'ingredient_added': await ingredient_name(
                db, organization_id, data.child_template_id
            ),
            'qty_per_batch': quantise(data.qty_per_batch, 4),
        },
    )
    return line


async def delete_bom_line(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    line_id: UUID,
    user: UserContextDTO | None = None,
) -> None:
    """Remove one ingredient line from a recipe."""
    line = await _get_line_of_recipe(db, organization_id, recipe_id, line_id)
    recipe = await get_recipe(db, organization_id, recipe_id)
    ingredient = await ingredient_name(db, organization_id, line.child_template_id)
    removed_qty = quantise(line.qty_per_batch, 4)
    await db.delete(line)
    await db.flush()
    if recipe is not None:
        await log_recipe_change(
            db,
            organization_id,
            user,
            recipe,
            AuditAction.UPDATE,
            {'ingredient_removed': ingredient, 'qty_per_batch': removed_qty},
        )


async def update_bom_line(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    line_id: UUID,
    data: BoMLineUpdate,
    user: UserContextDTO | None = None,
) -> BoMLine:
    """Update a BOM line in-place (qty_per_batch / uom_id / yield_loss / notes).

    This is the write the journal was missing hardest: the quantity here is
    what a run takes off the shelf, and the run reads it at completion.
    """
    line = await _get_line_of_recipe(db, organization_id, recipe_id, line_id)
    before = _line_shape(line, await _uom_symbol(db, line.uom_id, organization_id))

    # The same gate the add path runs: an edit is one more way to write a
    # line the shelf cannot be read in, and skipping it here made the
    # refusal bypassable by adding the line in one unit and patching it to
    # another afterwards.
    if data.uom_id is not None:
        await _refuse_unconvertible_unit(
            db, organization_id, line.child_template_id, data.uom_id
        )

    if data.qty_per_batch is not None:
        line.qty_per_batch = data.qty_per_batch
    if data.uom_id is not None:
        line.uom_id = data.uom_id
    if data.yield_loss_pct is not None:
        line.yield_loss_pct = data.yield_loss_pct
    if data.notes is not None:
        line.notes = data.notes

    await db.flush()
    changed = _changed_fields(
        before, _line_shape(line, await _uom_symbol(db, line.uom_id, organization_id))
    )
    recipe = await get_recipe(db, organization_id, recipe_id)
    if changed and recipe is not None:
        await log_recipe_change(
            db,
            organization_id,
            user,
            recipe,
            AuditAction.UPDATE,
            {
                'ingredient': await ingredient_name(
                    db, organization_id, line.child_template_id
                ),
                **changed,
            },
        )
    return line


# ---------------------------------------------------------------------------
# Cost lines
# ---------------------------------------------------------------------------


async def create_cost_line(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    data: RecipeCostLineCreate,
    user: UserContextDTO | None = None,
) -> MakerRecipeCostLine:
    recipe = await get_recipe(db, organization_id, recipe_id)
    if recipe is None:
        raise EntityNotFoundError('maker_recipe', f'Recipe {recipe_id} not found')

    cost_line = MakerRecipeCostLine(
        recipe_id=recipe_id,
        organization_id=organization_id,
        kind=data.kind,
        label=data.label,
        amount=data.amount,
        sort_order=data.sort_order,
    )
    db.add(cost_line)
    await db.flush()
    await log_recipe_change(
        db,
        organization_id,
        user,
        recipe,
        AuditAction.UPDATE,
        {'cost_line_added': data.label, 'amount': quantise(data.amount, 2)},
    )
    return cost_line


async def update_cost_line(
    db: AsyncSession,
    organization_id: UUID,
    line_id: UUID,
    data: RecipeCostLineUpdate,
    user: UserContextDTO | None = None,
) -> MakerRecipeCostLine:

    result = await db.execute(
        select(MakerRecipeCostLine).where(
            MakerRecipeCostLine.id == line_id,
            MakerRecipeCostLine.organization_id == organization_id,
        )
    )
    cost_line = result.scalar_one_or_none()
    if cost_line is None:
        raise EntityNotFoundError('cost_line', f'Cost line {line_id} not found')

    before = _cost_line_shape(cost_line)

    if data.kind is not None:
        cost_line.kind = data.kind
    if data.label is not None:
        cost_line.label = data.label
    if data.amount is not None:
        cost_line.amount = data.amount
    if data.sort_order is not None:
        cost_line.sort_order = data.sort_order

    await db.flush()
    changed = _changed_fields(before, _cost_line_shape(cost_line))
    recipe = await get_recipe(db, organization_id, cost_line.recipe_id)
    if changed and recipe is not None:
        await log_recipe_change(
            db,
            organization_id,
            user,
            recipe,
            AuditAction.UPDATE,
            {'cost_line': cost_line.label, **changed},
        )
    return cost_line


async def delete_cost_line(
    db: AsyncSession,
    organization_id: UUID,
    line_id: UUID,
    user: UserContextDTO | None = None,
) -> None:
    result = await db.execute(
        select(MakerRecipeCostLine).where(
            MakerRecipeCostLine.id == line_id,
            MakerRecipeCostLine.organization_id == organization_id,
        )
    )
    cost_line = result.scalar_one_or_none()
    if cost_line is None:
        raise EntityNotFoundError('cost_line', f'Cost line {line_id} not found')
    recipe = await get_recipe(db, organization_id, cost_line.recipe_id)
    label, amount = cost_line.label, quantise(cost_line.amount, 2)
    await db.delete(cost_line)
    await db.flush()
    if recipe is not None:
        await log_recipe_change(
            db,
            organization_id,
            user,
            recipe,
            AuditAction.UPDATE,
            {'cost_line_removed': label, 'amount': amount},
        )


# ---------------------------------------------------------------------------
# Catalog (GET /maker/recipes)
# ---------------------------------------------------------------------------


async def list_catalog(
    db: AsyncSession,
    organization_id: UUID,
    *,
    search: str | None = None,
    output_template_id: UUID | None = None,
    sort: str = 'newest',
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[MakerRecipe], int]:
    """List recipes enriched with catalog data (last_unit_cost, stock, etc.).

    ``output_template_id`` narrows the list to one product's formulas.
    """
    base_where = [MakerRecipe.organization_id == organization_id]
    if search:
        base_where.append(MakerRecipe.name.ilike(f'%{escape_ilike(search)}%'))
    if output_template_id is not None:
        base_where.append(MakerRecipe.output_template_id == output_template_id)

    stmt = select(MakerRecipe).where(*base_where)
    if sort == 'oldest':
        stmt = stmt.order_by(MakerRecipe.created_at.asc())
    elif sort == 'name':
        stmt = stmt.order_by(MakerRecipe.name.asc())
    else:
        stmt = stmt.order_by(MakerRecipe.created_at.desc())

    return await paginate_async(db, stmt, limit=limit, offset=offset)


@dataclass(frozen=True)
class LastProduction:
    """What the most recent completed run of a recipe cost, and how well.

    ``uncosted_ingredients`` is how many of that run's ingredients had no
    known purchase rate. Completion prices those at zero so the run can
    finish, which means a total of 0 is what "nobody knows" looks like once
    it reaches the catalog — indistinguishable, until this count, from a
    product that genuinely costs nothing to make.
    """

    unit_cost: Decimal | None
    completed_at: datetime | None
    uncosted_ingredients: int = 0


async def get_last_unit_costs(
    db: AsyncSession,
    organization_id: UUID,
    recipe_ids: list[UUID],
) -> dict[UUID, LastProduction]:
    """Batch-load the last completed run of each recipe.

    Only recipes with at least one COMPLETED order are included. Avoids N+1:
    one query for the orders, one for the lines that had no cost rate.
    """
    if not recipe_ids:
        return {}

    result = await db.execute(
        select(
            ProductionOrder.id,
            ProductionOrder.recipe_id,
            ProductionOrder.total_cost,
            ProductionOrder.planned_qty,
            ProductionOrder.actual_qty,
            ProductionOrder.completed_at,
        )
        .where(
            ProductionOrder.organization_id == organization_id,
            ProductionOrder.recipe_id.in_(recipe_ids),
            ProductionOrder.status == 'COMPLETED',
        )
        .order_by(
            ProductionOrder.recipe_id,
            ProductionOrder.completed_at.desc().nullslast(),
        )
    )
    rows = result.all()

    latest: dict[UUID, Any] = {}
    for row in rows:
        latest.setdefault(row.recipe_id, row)

    uncosted = await _uncosted_line_counts(db, [row.id for row in latest.values()])

    costs: dict[UUID, LastProduction] = {}
    for rid, row in latest.items():
        # unit_cost = total_cost / actual_qty (fallback to planned).
        effective_qty = row.actual_qty or row.planned_qty
        if effective_qty and effective_qty > 0 and row.total_cost is not None:
            # Quantize so the API never emits scientific-notation Decimals
            # (e.g. Decimal('0E+1') for a zero-cost division).
            unit_cost = quantise(row.total_cost / effective_qty, 4)
        else:
            unit_cost = None
        costs[rid] = LastProduction(
            unit_cost=unit_cost,
            completed_at=row.completed_at,
            uncosted_ingredients=uncosted.get(row.id, 0),
        )
    return costs


async def _uncosted_line_counts(
    db: AsyncSession, order_ids: list[UUID]
) -> dict[UUID, int]:
    """How many ingredients each run consumed without a known cost rate.

    The cost is written per line at completion — what the layers that line
    consumed actually cost, or nothing at all when they could not say — so
    the answer is already recorded and does not have to be re-derived from
    prices that have since moved.
    """
    if not order_ids:
        return {}

    rows = await db.execute(
        select(
            ProductionOrderLine.production_order_id,
            func.count(ProductionOrderLine.id),
        )
        .where(
            ProductionOrderLine.production_order_id.in_(order_ids),
            ProductionOrderLine.unit_cost_snapshot.is_(None),
        )
        .group_by(ProductionOrderLine.production_order_id)
    )
    return {row[0]: row[1] for row in rows.all()}


# ---------------------------------------------------------------------------
# Module settings
# ---------------------------------------------------------------------------


async def get_settings(
    db: AsyncSession,
    organization_id: UUID,
    *,
    for_update: bool = False,
) -> MakerModuleSettings:
    """Return settings for the org; a missing row reads as all defaults.

    A read takes no lock and never writes: the catalogue and the settings
    screen used to take the row lock by default, so two people opening the
    catalogue waited on each other and the first visit of an organization
    wrote a row from a GET. A caller about to act on a setting, or change
    one, asks for ``for_update=True``: that holds the row until its
    transaction ends and creates it with the defaults when absent (upsert).

    Row creation is serialised with an advisory lock: ``SELECT ... FOR
    UPDATE`` cannot lock a row that does not exist yet, so two concurrent
    first requests would both INSERT and one would fail the pkey
    constraint (observed as a 500 when parallel E2E specs created the
    first production order for an org).
    """
    if for_update:
        await acquire_advisory_lock(db, f'maker_settings:{organization_id}')
    stmt = select(MakerModuleSettings).where(
        MakerModuleSettings.organization_id == organization_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        if not for_update:
            # Read-only path: never write. The unsaved instance answers with
            # the values the insert would have written, timestamps included,
            # so a reader cannot tell "no row yet" from "a row of defaults".
            return MakerModuleSettings(
                organization_id=organization_id,
                **{
                    column.key: column.default.arg(None)
                    if column.default.is_callable
                    else column.default.arg
                    for column in MakerModuleSettings.__table__.columns
                    if column.default is not None
                },
            )
        settings = MakerModuleSettings(organization_id=organization_id)
        db.add(settings)
        await db.flush()
    return settings


async def update_settings(
    db: AsyncSession,
    organization_id: UUID,
    reference_direction: str | None = None,
    allow_overproduction: bool | None = None,
    availability_check_scope: str | None = None,
    create_on_shortage_strategy: str | None = None,
) -> MakerModuleSettings:
    settings = await get_settings(db, organization_id, for_update=True)
    if reference_direction is not None:
        settings.reference_direction = reference_direction
    if allow_overproduction is not None:
        settings.allow_overproduction = allow_overproduction
    if availability_check_scope is not None:
        settings.availability_check_scope = availability_check_scope
    if create_on_shortage_strategy is not None:
        settings.create_on_shortage_strategy = create_on_shortage_strategy
    await db.flush()
    return settings
