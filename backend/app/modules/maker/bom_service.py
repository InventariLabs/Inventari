"""BOM (Bill of Materials) service — CRUD + multi-level expand + cycle detection.

All functions are async and operate on an ``AsyncSession``. Cross-location
consumption of ingredients is handled by ``stock_consumption.py``.

Since the recipe model, BOM lines belong to ``maker_recipes``.
The legacy ``parent_template_id`` column is kept as a denormalised copy of
``recipe.output_template_id`` for backward-compatible API endpoints.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from .models import BoMLine, MakerRecipe

_MAX_DEPTH = 10

#: ``maker_recipes.name`` is ``String(200)``; a product template's name holds 255.
_RECIPE_NAME_MAX = 200


# ---------------------------------------------------------------------------
# Recipe helpers
# ---------------------------------------------------------------------------


def first_default_lock_key(organization_id: UUID, output_template_id: UUID) -> str:
    """The advisory lock under which "first recipe → default" is decided.

    Every path that inserts a maker recipe whose default-ness depends on
    what already exists holds this lock per (org, template): inside it the
    count-then-insert is serial, so two concurrent first-recipes cannot
    both claim default (the partial unique index would reject one with a
    500, not a clean answer) and a default-less template cannot stay
    default-less behind the caller's back.
    """
    return f'maker-recipe:{organization_id}:{output_template_id}'


async def find_default_recipe(
    db: AsyncSession,
    organization_id: UUID,
    output_template_id: UUID,
) -> MakerRecipe | None:
    """Return the default recipe for *output_template_id*, or ``None``."""
    result = await db.execute(
        select(MakerRecipe).where(
            MakerRecipe.organization_id == organization_id,
            MakerRecipe.output_template_id == output_template_id,
            MakerRecipe.is_default.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _find_default_recipes_batch(
    db: AsyncSession,
    organization_id: UUID,
    output_template_ids: Iterable[UUID],
) -> dict[UUID, MakerRecipe]:
    """Return ``{output_template_id: default recipe}`` in one query.

    Explosion walks a whole level at a time; asking for each child's
    default recipe one by one turns every sibling line into its own
    round-trip (plus a lazy ``lines`` load per hit). ``selectinload``
    hydrates the ``lines`` collections in the same round-trip batch.
    """
    ids = list(dict.fromkeys(output_template_ids))
    if not ids:
        return {}
    stmt = (
        select(MakerRecipe)
        .options(selectinload(MakerRecipe.lines))
        .where(
            MakerRecipe.organization_id == organization_id,
            MakerRecipe.output_template_id.in_(ids),
            MakerRecipe.is_default.is_(True),
        )
    )
    rows = (await db.scalars(stmt)).all()
    return {row.output_template_id: row for row in rows}


async def get_or_create_default_recipe(
    db: AsyncSession,
    organization_id: UUID,
    output_template_id: UUID,
) -> MakerRecipe:
    """Return the default recipe for a template, auto-creating if absent.

    Used by the legacy ``/bom/*`` adapter endpoints (compatibility).
    The auto-created recipe has ``batch_yield_qty = 1`` (legacy semantics)
    and is the default — the function's name is its contract.

    The find-then-insert runs under the same advisory lock POST /recipes
    holds (``maker-recipe:{org}:{template}``), so a concurrent create
    cannot slip a default in between the lookup and the insert — without
    the lock two such inserts died on ``uq_recipe_org_template_name``
    (both rows carry the template's name, so the (org, template, name)
    unique constraint fires; the partial default index could not reject
    them while no default existed). The row is
    built directly, not through ``RecipeCreate``, because nothing in it is
    user input to validate: the name is the template's, the quantity is
    legacy-fixed at 1, and ``is_default=True`` is this function's contract.
    A template name may run to 255 characters and a recipe name holds 200,
    so the template's name is cut to fit: the recipe is a default label the
    reader can rename, and refusing a move over it would be the wrong
    trade. When recipes exist
    but none is default (a state the app cannot reach on its own), the
    insert becomes the default the template was missing — that is the
    guarantee, not a side effect.
    """
    from app.core.db_utils import acquire_advisory_lock

    await acquire_advisory_lock(
        db, first_default_lock_key(organization_id, output_template_id)
    )

    recipe = await find_default_recipe(db, organization_id, output_template_id)
    if recipe is not None:
        return recipe

    template = await core_api.product_templates.get_async(
        db, organization_id, output_template_id
    )
    name = (template.name if template else 'Unnamed')[:_RECIPE_NAME_MAX]

    recipe = MakerRecipe(
        organization_id=organization_id,
        output_template_id=output_template_id,
        name=name,
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    await db.flush()
    return recipe


# ---------------------------------------------------------------------------
# BOM line queries (legacy API compat — keyed by parent_template_id)
# ---------------------------------------------------------------------------


async def list_lines(
    db: AsyncSession,
    organization_id: UUID,
    parent_template_id: UUID,
    *,
    recipe_id: UUID | None = None,
) -> list[BoMLine]:
    """The BOM lines of one recipe of *parent_template_id*, organization-scoped.

    *recipe_id* names the recipe; without it, the product's default recipe —
    the one the explosion walks for a sub-assembly. A product with variants
    has a recipe for each, and keyed by the product alone the answer was all
    of them in one list: the tree on one variant's page showed the other
    variants' ingredients as its own. A *recipe_id* of another product
    answers nothing.
    """
    stmt = select(BoMLine).where(
        BoMLine.organization_id == organization_id,
        BoMLine.parent_template_id == parent_template_id,
    )
    if recipe_id is not None:
        stmt = stmt.where(BoMLine.recipe_id == recipe_id)
    else:
        stmt = stmt.join(MakerRecipe, MakerRecipe.id == BoMLine.recipe_id).where(
            MakerRecipe.is_default.is_(True)
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def summarize_lines(
    db: AsyncSession,
    organization_id: UUID,
    parent_template_ids: list[UUID],
) -> dict[UUID, int]:
    """Return {parent_template_id: line_count} for templates that have a BOM.

    Templates with no lines are omitted. Used by the batched /bom/summary
    endpoint for product-list badges (no N+1 queries).
    """
    if not parent_template_ids:
        return {}
    stmt = (
        select(BoMLine.parent_template_id, func.count(BoMLine.id))
        .where(
            BoMLine.organization_id == organization_id,
            BoMLine.parent_template_id.in_(parent_template_ids),
        )
        .group_by(BoMLine.parent_template_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row.parent_template_id: row[1] for row in rows}


async def list_parents(
    db: AsyncSession,
    organization_id: UUID,
) -> list[tuple[UUID, int]]:
    """List recipes: (parent_template_id, line_count) per parent with a BOM.

    Names are resolved by the caller via CoreAPI (services must not import
    Core models).
    """
    stmt = (
        select(BoMLine.parent_template_id, func.count(BoMLine.id))
        .where(BoMLine.organization_id == organization_id)
        .group_by(BoMLine.parent_template_id)
    )
    rows = (await db.execute(stmt)).all()
    return [(row.parent_template_id, row[1]) for row in rows]


async def list_where_used(
    db: AsyncSession,
    organization_id: UUID,
    child_template_id: UUID,
) -> list[tuple[UUID, str, UUID, Decimal, str]]:
    """Return recipes that consume ``child_template_id``.

    Reverse BOM edge via ``maker_bom_lines.child_template_id`` JOIN
    ``maker_recipes`` — direct usage only, no recursion (a cycle in the BOM
    graph therefore cannot confuse the result; each edge is reported once).
    Returns ``(recipe_id, recipe_name, output_template_id, qty_per_batch,
    unit)`` sorted by recipe name. Names of the outputs are resolved by the
    caller via CoreAPI (services must not import Core models).
    """
    stmt = (
        select(
            BoMLine.recipe_id,
            MakerRecipe.name,
            MakerRecipe.output_template_id,
            BoMLine.qty_per_batch,
            BoMLine.unit,
        )
        .join(MakerRecipe, MakerRecipe.id == BoMLine.recipe_id)
        .where(
            BoMLine.organization_id == organization_id,
            MakerRecipe.organization_id == organization_id,
            BoMLine.child_template_id == child_template_id,
        )
        .order_by(MakerRecipe.name.asc(), BoMLine.qty_per_batch.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        (row.recipe_id, row.name, row.output_template_id, row.qty_per_batch, row.unit)
        for row in rows
    ]


def _validate_line_parent(recipe: MakerRecipe, parent_template_id: UUID) -> None:
    """Enforce the line-parent invariant: a line's parent is its recipe's output.

    ``parent_template_id`` is a denormalised copy of
    ``recipe.output_template_id`` kept for legacy API compatibility. A
    divergence would silently corrupt the legacy ``/bom`` endpoints and the
    multi-level explode, so every line write validates the pair before
    flush.

    Defensive, not a refusal: its only caller (``bom_tree.move_line``) passes
    the recipe ``get_or_create_default_recipe`` just resolved *for* that
    parent, so the pair matches by construction and a reader cannot reach
    this raise. It therefore keeps a plain ``ValueError`` and speaks in the
    module's identifiers rather than in a reader's language.
    """
    if recipe.output_template_id != parent_template_id:
        raise ServiceRejectionError('bom_line_parent_mismatch')


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


async def ensure_no_cycle(
    db: AsyncSession,
    organization_id: UUID,
    parent_id: UUID,
    child_id: UUID,
) -> None:
    """Walk the descendant graph from ``child_id``; raise if ``parent_id`` is reachable.

    Descendants are resolved via default recipes (template-walk). Adding an
    edge parent → child must not make ``parent`` its own descendant.
    """
    visited: set[UUID] = set()
    stack: list[UUID] = [child_id]
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        if cur == parent_id:
            # This refusal surfaces under the composition form's error slot,
            # like its self-reference sibling in the recipe service — the
            # keyed rejection carries the glossary's spelling of the module
            # noun (BOM, per docs/MODULE_NAMES.md) into every language.
            raise ServiceRejectionError('bom_line_cycle')
        visited.add(cur)
        recipe = await find_default_recipe(db, organization_id, cur)
        if recipe is not None:
            for line in recipe.lines:
                stack.append(line.child_template_id)


# ---------------------------------------------------------------------------
# Explode (recipe-aware, batch math)
# ---------------------------------------------------------------------------


async def explode(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
) -> list[tuple[UUID, Decimal, str]]:
    """Resolve a multi-level BOM into a flat list of (child, qty, unit).

    Uses the default recipe for *template_id*. Cycles raise ``ValueError``.
    Depth is bounded to ``_MAX_DEPTH`` levels.

    Batch math: ``batches = qty / recipe.batch_yield_qty``;
    per-line ``effective_qty = batches * qty_per_batch * (1 + yield_loss_pct/100)``.
    For migrated recipes (yield=1) the result is identical to the legacy
    per-unit formula.
    """
    detailed = await explode_with_uom(db, organization_id, template_id, qty)
    return [(child_id, child_qty, unit) for child_id, child_qty, unit, _ in detailed]


async def explode_with_uom(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
) -> list[tuple[UUID, Decimal, str, UUID | None]]:
    """Like :func:`explode` but keeps each leaf's line ``uom_id``.

    The unit a line is written in is not decoration: a line saying 500 g
    against stock kept in kilograms is 0.5 of the stock's unit, and consuming
    the bare 500 takes half a tonne. Availability already reads it (through
    ``explode_by_recipe_with_uom``); consumption has to read it too, and only
    the by-recipe path offered it.
    """
    recipe = await find_default_recipe(db, organization_id, template_id)
    if recipe is None:
        return []
    batches = Decimal(str(qty)) / recipe.batch_yield_qty
    return await _explode_recipe(
        db, organization_id, recipe, batches, depth=0, _seen=None
    )


async def resolve_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
) -> MakerRecipe:
    """Resolve a recipe id the caller named, or refuse in the reader's language.

    The cost-breakdown endpoint takes ``recipe_id`` straight from the query
    string, so an id this organization does not have is a refusal a reader
    reaches by editing a URL — it answers with the module's own sentence for
    a missing recipe, the same one ``create_order`` uses.
    """
    result = await db.execute(
        select(MakerRecipe).where(
            MakerRecipe.id == recipe_id,
            MakerRecipe.organization_id == organization_id,
        )
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise ServiceRejectionError('production_recipe_not_found', recipe_id=recipe_id)
    return recipe


async def explode_by_recipe_with_uom(
    db: AsyncSession,
    organization_id: UUID,
    recipe_id: UUID,
    qty: Decimal,
) -> list[tuple[UUID, Decimal, str, UUID | None]]:
    """Like ``explode_by_recipe`` but keeps each leaf's line ``uom_id``.

    Availability checks need the structural UoM of the line that produced a
    leaf — including leaves reached through nested sub-assemblies — to convert
    stock units correctly.
    """
    recipe = await resolve_recipe(db, organization_id, recipe_id)
    batches = Decimal(str(qty)) / recipe.batch_yield_qty
    return await _explode_recipe(
        db, organization_id, recipe, batches, depth=0, _seen=None
    )


async def explode_by_recipes_with_uom(
    db: AsyncSession,
    organization_id: UUID,
    recipe_ids: Iterable[UUID],
) -> dict[UUID, list[tuple[UUID, Decimal, str, UUID | None]]]:
    """Explode many recipes, one batch each, in one round of queries.

    The per-recipe exploder pays a recipe read, a lines load and a
    child-recipe lookup per call — the price of one order's check, but a
    page of drafts with a recipe each turned it into a round-trip per row.
    Here the page's recipes arrive in one select and the shared child
    cache is warmed a level at a time for the whole set, so the cost grows
    with the page's depth, not its row count. The per-recipe result is
    what ``explode_by_recipe_with_uom`` returns at one batch; a recipe
    this organization does not have gets no entry.
    """
    ids = list(dict.fromkeys(recipe_ids))
    if not ids:
        return {}
    stmt = select(MakerRecipe).where(
        MakerRecipe.id.in_(ids), MakerRecipe.organization_id == organization_id
    )
    tops = {recipe.id: recipe for recipe in (await db.scalars(stmt)).all()}

    # A child resolved for one recipe serves every recipe that names it,
    # and a resolved absence is remembered too.
    child_cache = await _warm_child_cache(db, organization_id, tops.values())

    return {
        recipe_id: await _explode_recipe(
            db,
            organization_id,
            recipe,
            Decimal('1'),
            depth=0,
            _seen=None,
            _child_cache=child_cache,
        )
        for recipe_id, recipe in tops.items()
    }


async def _explode_recipe(
    db: AsyncSession,
    organization_id: UUID,
    recipe: MakerRecipe,
    batches: Decimal,
    *,
    depth: int,
    _seen: set[UUID] | None,
    _child_cache: dict[UUID, MakerRecipe | None] | None = None,
) -> list[tuple[UUID, Decimal, str, UUID | None]]:
    # Depth is reachable: nothing bounds nesting on the write side (unlike
    # cycles, which ``ensure_no_cycle`` refuses at every door), so a chain
    # built past the limit refuses in the reader's language here and in
    # ``bom_tree.get_tree``.
    if depth > _MAX_DEPTH:
        raise ServiceRejectionError('bom_depth_exceeded', max_depth=_MAX_DEPTH)
    seen = _seen if _seen is not None else set()
    if recipe.output_template_id in seen:
        # Defensive: a persisted cycle (which no write path can create)
        # would land here, and no reader should ever see it — the literal
        # names the input data, not a person's action.
        raise ServiceRejectionError(
            'bom_cycle_detected', template_id=recipe.output_template_id
        )
    seen_with_self = seen | {recipe.output_template_id}

    # Fetch every child's default recipe for this level in one query —
    # a query per sibling line made explosion cost grow with the number
    # of lines instead of the number of levels. A batch caller passes a
    # shared cache instead, so the page resolves a child once for all
    # recipes that name it.
    child_recipes: dict[UUID, MakerRecipe | None]
    if _child_cache is not None:
        child_recipes = await _child_recipes_through_cache(
            db, organization_id, recipe.lines, _child_cache
        )
    else:
        found = await _find_default_recipes_batch(
            db,
            organization_id,
            (line.child_template_id for line in recipe.lines),
        )
        child_recipes = dict(found)

    flat: list[tuple[UUID, Decimal, str, UUID | None]] = []
    for line in recipe.lines:
        effective_qty = (
            batches
            * line.qty_per_batch
            * (Decimal('1') + line.yield_loss_pct / Decimal('100'))
        )
        child_recipe = child_recipes.get(line.child_template_id)
        if child_recipe is not None:
            child_batches = effective_qty / child_recipe.batch_yield_qty
            sub = await _explode_recipe(
                db,
                organization_id,
                child_recipe,
                child_batches,
                depth=depth + 1,
                _seen=seen_with_self,
                _child_cache=_child_cache,
            )
            if sub:
                flat.extend(sub)
            else:
                # Sub-assembly with no ingredients — treat as leaf.
                flat.append(
                    (line.child_template_id, effective_qty, line.unit, line.uom_id)
                )
        else:
            flat.append((line.child_template_id, effective_qty, line.unit, line.uom_id))
    return flat


async def _in_stock_units(
    db: AsyncSession,
    organization_id: UUID,
    flat: list[tuple[UUID, Decimal, str, UUID | None]],
) -> list[tuple[UUID, Decimal, str]]:
    """Re-express each exploded line in the ingredient's own stock unit.

    A line whose unit matches the stock's, or where either side names no unit,
    passes through untouched — a bare number against a bare number is how every
    product predating units is written, and refusing those would stop
    production for all of them.

    A pair that cannot be converted (grams against pieces, with nothing saying
    what a piece weighs) also passes through, because the availability check
    reaches that conclusion first and refuses the run; and ``add_bom_line``
    refuses to write such a line at all. Converting here would be inventing a
    ratio; leaving it is the same answer the rest of the module gives.
    """
    uoms = {
        uom.id: uom
        for uom in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, [child_id for child_id, _q, _u, _l in flat]
    )
    return _convert_flat_to_stock_units(flat, uoms, templates)


def _convert_flat_to_stock_units(
    flat: list[tuple[UUID, Decimal, str, UUID | None]],
    uoms: dict[UUID, Any],
    templates: dict[UUID, Any],
) -> list[tuple[UUID, Decimal, str]]:
    """The unit conversion ``_in_stock_units`` performs, over shared caches.

    Split out so a batch of recipes can load the unit catalogue and the
    ingredient templates once instead of once per recipe.
    """
    converted: list[tuple[UUID, Decimal, str]] = []
    for child_id, qty, unit, line_uom_id in flat:
        template = templates.get(child_id)
        stock_uom_id = template.uom_id if template else None
        if line_uom_id is None and stock_uom_id is not None:
            # A line that names no unit is counted in its ingredient's: that is
            # the number its stock move takes off the shelf, so that is the
            # unit it is labelled with. Its free-text unit said "kg" beside a
            # move of the same number in pieces.
            stock_uom = uoms.get(stock_uom_id)
            converted.append((child_id, qty, stock_uom.symbol if stock_uom else unit))
            continue
        if line_uom_id is None or stock_uom_id is None or line_uom_id == stock_uom_id:
            converted.append((child_id, qty, unit))
            continue
        stock_uom = uoms.get(stock_uom_id)
        qty_in_stock, ok = core_api.uoms.convert_quantity(
            qty, uoms.get(line_uom_id), stock_uom
        )
        # The unit travels with the number: an order line saying "0.5" under a
        # heading of "g" would be the same lie in a smaller font.
        converted.append(
            (
                child_id,
                qty_in_stock,
                stock_uom.symbol if ok and stock_uom else unit,
            )
        )
    return converted


async def explode_recipes_in_stock_units(
    db: AsyncSession,
    organization_id: UUID,
    requests: list[tuple[MakerRecipe, Decimal]],
) -> dict[UUID, list[tuple[UUID, Decimal, str]]]:
    """Explode many recipes in one pass, sharing every cache across the batch.

    A catalogue page of never-run recipes used to pay the whole explosion per
    recipe — child-recipe lookups, the unit catalogue, the ingredient
    templates, the rates — and the page's query count grew with the page
    size. Here the child-recipe map is warmed a level at a time for the
    whole page, and the unit and template catalogues load once for the
    union of the batch's leaves.
    """
    child_cache = await _warm_child_cache(
        db, organization_id, (recipe for recipe, _qty in requests)
    )

    flats: dict[UUID, list[tuple[UUID, Decimal, str, UUID | None]]] = {}
    for recipe, qty in requests:
        if not recipe.batch_yield_qty:
            flats[recipe.id] = []
            continue
        batches = Decimal(str(qty)) / recipe.batch_yield_qty
        flats[recipe.id] = await _explode_recipe(
            db,
            organization_id,
            recipe,
            batches,
            depth=0,
            _seen=None,
            _child_cache=child_cache,
        )

    uoms = {
        uom.id: uom
        for uom in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    leaf_ids = sorted({cid for flat in flats.values() for (cid, *_rest) in flat})
    templates = await core_api.product_templates.get_many_async(
        db, organization_id, leaf_ids
    )
    return {
        recipe_id: _convert_flat_to_stock_units(flat, uoms, templates)
        for recipe_id, flat in flats.items()
    }


async def _warm_child_cache(
    db: AsyncSession,
    organization_id: UUID,
    recipes: Iterable[MakerRecipe],
) -> dict[UUID, MakerRecipe | None]:
    """Resolve every sub-recipe under *recipes*, one query per BoM level.

    Warming only the page's own lines left each deeper level to the walk,
    which met it one recipe at a time: a page of three-level formulas with
    different intermediates paid a query per recipe per level. Walking the
    whole page breadth-first asks once per level for every child not yet
    resolved, so the walk that follows never reaches the database. A
    resolved absence is recorded too, so a leaf is not asked about again.
    Already-resolved children are skipped, so a persisted cycle ends the
    loop here and is refused by the walk with its own message. The levels
    stop where the walk refuses, one past ``_MAX_DEPTH``: a chain built
    deeper than that would otherwise be fetched to its end before the walk
    turned it away.
    """
    cache: dict[UUID, MakerRecipe | None] = {}
    frontier = list(recipes)
    for _level in range(_MAX_DEPTH + 1):
        missing = sorted(
            {
                line.child_template_id
                for recipe in frontier
                for line in recipe.lines
                if line.child_template_id not in cache
            }
        )
        if not missing:
            break
        found = await _find_default_recipes_batch(db, organization_id, missing)
        for child_id in missing:
            cache[child_id] = found.get(child_id)
        frontier = list(found.values())
    return cache


async def _child_recipes_through_cache(
    db: AsyncSession,
    organization_id: UUID,
    lines: Iterable[BoMLine],
    cache: dict[UUID, MakerRecipe | None],
) -> dict[UUID, MakerRecipe | None]:
    """Resolve the lines' default recipes through a batch-wide cache.

    First time a child template is met its lookup runs (one query for every
    still-unresolved sibling); from then on the cached answer — a recipe or
    a resolved ``None`` — serves the whole batch.
    """
    missing = [
        line.child_template_id for line in lines if line.child_template_id not in cache
    ]
    if missing:
        found = await _find_default_recipes_batch(db, organization_id, missing)
        for child_id in missing:
            cache[child_id] = found.get(child_id)
    return {line.child_template_id: cache[line.child_template_id] for line in lines}


async def explode_in_stock_units(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    qty: Decimal,
    recipe_id: UUID | None = None,
) -> list[tuple[UUID, Decimal, str]]:
    """Explode a bill of materials and answer in each ingredient's stock unit.

    The conversion used to be a second step the caller had to remember, and
    two of them did not: the cost preview and the per-ingredient breakdown
    multiplied a rate held per kilogram by a quantity read in grams, so both
    were wrong by the factor between the units — a thousand, for the pair a
    kitchen uses most. Consumption converted; the numbers shown beside it did
    not, and the two disagreed about the same run.

    One entry point, so the question "in what unit is this number" has one
    answer for everything downstream of a formula.
    """
    flat = (
        await explode_by_recipe_with_uom(db, organization_id, recipe_id, qty)
        if recipe_id is not None
        else await explode_with_uom(db, organization_id, template_id, qty)
    )
    return await _in_stock_units(db, organization_id, flat)
