"""BOM tree + move operations for the multi-level editor.

- ``get_tree`` resolves the hierarchical BOM under a parent.
- ``move_line`` reparents an existing line under a new parent; validates
  ``unique(parent, child)``, ``parent ≠ child``, and cycles before write.

Cycle check mirrors ``bom_service.ensure_no_cycle`` but is run against the
persisted graph.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction
from app.core.exceptions import ServiceRejectionError

from . import bom_service
from .models import BoMLine


async def get_tree(
    db: AsyncSession,
    organization_id: UUID,
    parent_template_id: UUID,
    *,
    _visited: set[UUID] | None = None,
    _depth: int = 0,
) -> dict[str, Any]:
    """Return a recursive tree dict: ``{line, children: [...]}``.

    Each level is bounded by ``bom_service._MAX_DEPTH``; a graph deeper than
    the resolver's limit refuses through the error catalog. A cycle in the
    persisted graph — which ``ensure_no_cycle`` never lets a write create —
    raises a plain ``ValueError``. The function never traverses a
    template_id twice per branch (DFS path-based ``_visited``).
    """
    visited = _visited if _visited is not None else set()
    if _depth > bom_service._MAX_DEPTH:
        raise ServiceRejectionError(
            'bom_depth_exceeded', max_depth=bom_service._MAX_DEPTH
        )
    if parent_template_id in visited:
        raise ServiceRejectionError(
            'bom_cycle_detected', template_id=parent_template_id
        )

    visited = visited | {parent_template_id}
    lines = await bom_service.list_lines(db, organization_id, parent_template_id)

    children = []
    for line in lines:
        sub_tree = await get_tree(
            db,
            organization_id,
            line.child_template_id,
            _visited=visited,
            _depth=_depth + 1,
        )
        sub_tree['line'] = line
        children.append(sub_tree)

    return {'line': None, 'children': children}


async def move_line(
    db: AsyncSession,
    organization_id: UUID,
    line_id: UUID,
    new_parent_template_id: UUID,
    user: Any | None = None,
) -> BoMLine:
    """Reparent an existing BOM line under a new parent.

    Validates (in order):
    1. Line exists in the org (else ``bom_line_not_found``).
    2. New parent and child are distinct (CHECK ``ck_bom_no_self``).
    3. Moving the line would NOT make ``new_parent`` a descendant of the
       line's current child (cycle).
    4. The new parent's default recipe has no line for the child yet
       (UNIQUE ``(recipe_id, child_template_id)``); the default recipe is
       auto-created (yield=1) when the parent has none (legacy adapter
       semantics).

    On success the line's ``recipe_id`` is re-pointed to the new parent's
    default recipe together with ``parent_template_id``, so the moved line
    explodes under the NEW parent (line-parent invariant:
    ``parent_template_id == recipe.output_template_id``).
    """
    line = (
        await db.execute(
            select(BoMLine).where(
                BoMLine.id == line_id,
                BoMLine.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if line is None:
        raise ServiceRejectionError('bom_line_not_found')

    source_recipe_id = line.recipe_id

    if new_parent_template_id == line.child_template_id:
        # The reader can drag a line onto its own ingredient in the tree
        # editor, so this refusal reaches a screen — the same sentence as
        # its recipe-service sibling, which refuses the identical shape.
        raise ServiceRejectionError('bom_line_self_reference')

    await bom_service.ensure_no_cycle(
        db,
        organization_id,
        new_parent_template_id,
        line.child_template_id,
    )

    await db.flush()

    # Resolve the recipe the line will belong to after the move: the new
    # parent's default recipe. Auto-creating here (like ``add_line``) keeps
    # the legacy template-keyed API consistent for parents without a recipe.
    target_recipe = await bom_service.get_or_create_default_recipe(
        db, organization_id, new_parent_template_id
    )
    bom_service._validate_line_parent(target_recipe, new_parent_template_id)

    # Pre-check UNIQUE(recipe_id, child_template_id) BEFORE mutating the
    # line so the autoflush preceding our SELECT does not race with an
    # update that already collides. asyncpg surfaces unique violations as
    # raw asyncpg.UniqueViolationError that SQLAlchemy does not always wrap
    # into sqlalchemy.exc.IntegrityError — validating up-front avoids the
    # cross-driver catch mismatch and is cheap (indexed lookup).
    existing = (
        await db.execute(
            select(BoMLine.id)
            .where(
                BoMLine.organization_id == organization_id,
                BoMLine.recipe_id == target_recipe.id,
                BoMLine.child_template_id == line.child_template_id,
                BoMLine.id != line_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        # The reader dragged this line here, so they know both products: the
        # sentence says what happened, where the literal printed the two
        # template ids it was comparing.
        raise ServiceRejectionError('bom_line_already_exists')

    # Re-point BOTH the recipe and the denormalised parent — otherwise the
    # line would keep exploding under the OLD recipe.
    line.recipe_id = target_recipe.id
    line.parent_template_id = new_parent_template_id
    db.add(line)
    await db.flush()

    # One ingredient leaving one formula and joining another is two changes of
    # what a run will consume, so both recipes get an entry rather than the
    # destination alone.
    from . import recipe_service

    ingredient = await recipe_service.ingredient_name(
        db, organization_id, line.child_template_id
    )
    source = await recipe_service.get_recipe(db, organization_id, source_recipe_id)
    if source is not None and source.id != target_recipe.id:
        await recipe_service.log_recipe_change(
            db,
            organization_id,
            user,
            source,
            AuditAction.UPDATE,
            {'ingredient_moved_out': ingredient, 'to_recipe': target_recipe.name},
        )
    await recipe_service.log_recipe_change(
        db,
        organization_id,
        user,
        target_recipe,
        AuditAction.UPDATE,
        {
            'ingredient_moved_in': ingredient,
            'from_recipe': source.name if source is not None else None,
        },
    )
    return line
