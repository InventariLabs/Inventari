"""BOM (Bill of Materials) endpoints — read, tree, move and line delete.

Composing a formula happens under ``/maker/recipes/{id}/bom-lines``. The two
write endpoints that used to live here resolved a *product* to its default
recipe, so a product with a second formula could not be addressed at all —
they are gone, and with them the second editor screen that called them.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException
from app.core.module_sdk import PaginatedResponse
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from . import bom_tree, cost_breakdown, recipe_service
from ._schemas_bom import (
    BoMLineRead,
    BomMoveRequest,
    BoMParentItem,
    BoMSummaryItem,
    BoMSummaryResponse,
    BoMTemplateIdsResponse,
    BomTreeNode,
    BomTreeResponse,
    WhereUsedItem,
)
from ._schemas_breakdown import CostBreakdownResponse
from .bom_service import (
    list_lines,
    list_parents,
    list_where_used,
    summarize_lines,
)
from .maker_api import maker_api
from .models import BoMLine, MakerRecipe

router = APIRouter(prefix='/bom', tags=['maker'])


class _HasChildTemplateId(Protocol):
    """Structural type for ORM rows carrying a child_template_id (BoMLine, ProductionOrderLine)."""

    child_template_id: UUID


async def _attach_child_names(
    db: AsyncSession, org_id: UUID, lines: Sequence[_HasChildTemplateId]
) -> None:
    """Set transient child_template_name on line ORM objects for display."""
    ids = {line.child_template_id for line in lines}
    if not ids:
        return
    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    names = {t.id: t.name for t in templates}
    images = {t.id: t.image_url for t in templates}
    for line in lines:
        # ``child_template_name``/``child_template_image_url`` are transient,
        # non-persisted attributes that ``BoMLineRead.model_validate()``
        # picks up for display. ``setattr`` keeps them off the SQLAlchemy
        # model (unmapped annotations are rejected by Annotated Declarative
        # Table form).
        setattr(line, 'child_template_name', names.get(line.child_template_id))  # noqa: B010
        setattr(line, 'child_template_image_url', images.get(line.child_template_id))  # noqa: B010


def _collect_tree_lines(node: dict[str, Any], acc: list[BoMLine]) -> None:
    """Recursively collect BoMLine objects from a bom_tree.get_tree() dict."""
    line = node.get('line')
    if line is not None:
        acc.append(line)
    for child in node.get('children', []):
        _collect_tree_lines(child, acc)


@router.get(
    '/parents',
    response_model=PaginatedResponse[BoMParentItem],
)
async def get_bom_parents(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[BoMParentItem]:
    """List all recipes in the organization (parents that have >=1 BOM line)."""
    rows = await list_parents(db, org_id)
    if not rows:
        return PaginatedResponse[BoMParentItem].from_full_list(
            [], offset=offset, limit=limit
        )
    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    names = {t.id: t.name for t in templates}
    items = [
        BoMParentItem(
            template_id=tid,
            name=names.get(tid, str(tid)),
            line_count=count,
        )
        for tid, count in rows
    ]
    items.sort(key=lambda item: item.name)
    return PaginatedResponse[BoMParentItem].from_full_list(
        items, offset=offset, limit=limit
    )


@router.get(
    '/template-ids',
    response_model=BoMTemplateIdsResponse,
)
async def get_template_ids_with_bom(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BoMTemplateIdsResponse:
    """Every product template in the organization that has a formula.

    Feeds the "has a formula" filter on the product list: the table is
    virtualised, so it cannot decide row by row from data it has not fetched.
    """
    return BoMTemplateIdsResponse(
        template_ids=await maker_api.list_template_ids_with_bom_async(db, org_id)
    )


@router.get(
    '/summary',
    response_model=BoMSummaryResponse,
)
async def get_bom_summary(
    template_ids: str = Query('', description='Comma-separated template UUIDs'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BoMSummaryResponse:
    """Batched BOM existence + line count for a list of templates.

    Returns one entry per template that has >=1 BOM line. Templates with no
    BOM are omitted. Used to render 'has BOM' badges in product lists without
    N+1 queries.
    """
    raw = [tid.strip() for tid in template_ids.split(',') if tid.strip()]
    if not raw:
        return BoMSummaryResponse(items=[])
    ids = [UUID(tid) for tid in raw]
    counts = await summarize_lines(db, org_id, ids)

    # Batch-resolve default recipe ids for link targets (no N+1).
    default_recipe_ids: dict[UUID, UUID | None] = {}
    if ids:
        result = await db.execute(
            select(MakerRecipe.id, MakerRecipe.output_template_id).where(
                MakerRecipe.organization_id == org_id,
                MakerRecipe.output_template_id.in_(ids),
                MakerRecipe.is_default.is_(True),
            )
        )
        default_recipe_ids = {row.output_template_id: row.id for row in result.all()}

    return BoMSummaryResponse(
        items=[
            BoMSummaryItem(
                template_id=template_id,
                line_count=count,
                default_recipe_id=default_recipe_ids.get(template_id),
            )
            for template_id, count in counts.items()
        ]
    )


# NOTE: this static route MUST stay registered before ``/{template_id}`` —
# FastAPI matches routes in order and would otherwise 422 "where-used" as
# an invalid UUID path parameter.
@router.get(
    '/where-used',
    response_model=PaginatedResponse[WhereUsedItem],
)
async def get_where_used(
    template_id: UUID = Query(..., description='Child template used as an ingredient'),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[WhereUsedItem]:
    """Reverse BOM edge: which recipes consume ``template_id``.

    Direct usage only (a single JOIN over ``maker_bom_lines`` ×
    ``maker_recipes``, no recursion — sub-assemblies are listed when the
    template is their direct ingredient, not transitively). Empty ``items``
    when the template is not used anywhere. Org-scoped.
    """
    rows = await list_where_used(db, org_id, template_id)
    if not rows:
        return PaginatedResponse[WhereUsedItem].from_full_list(
            [], offset=offset, limit=limit
        )

    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    names = {t.id: t.name for t in templates}
    return PaginatedResponse[WhereUsedItem].from_full_list(
        [
            WhereUsedItem(
                recipe_id=recipe_id,
                recipe_name=recipe_name,
                output_template_id=output_template_id,
                output_template_name=names.get(output_template_id),
                qty_per_batch=qty_per_batch,
                unit=unit,
            )
            for recipe_id, recipe_name, output_template_id, qty_per_batch, unit in rows
        ],
        offset=offset,
        limit=limit,
    )


@router.get(
    '/{template_id}',
    response_model=PaginatedResponse[BoMLineRead],
)
async def get_bom_lines(
    template_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[BoMLineRead]:
    lines = await list_lines(db, org_id, template_id)
    await _attach_child_names(db, org_id, lines)
    return PaginatedResponse[BoMLineRead].from_full_list(
        [BoMLineRead.model_validate(line) for line in lines],
        offset=offset,
        limit=limit,
    )


@router.get(
    '/{template_id}/cost-estimate',
    response_model=CostBreakdownResponse,
)
async def get_bom_cost_estimate(
    template_id: UUID,
    recipe_id: UUID | None = Query(
        None,
        description=(
            'Compute for this formula instead of the template default — a '
            "variant asks about its own ingredients, not the default's."
        ),
    ),
    qty: Decimal = Query(
        Decimal('1'),
        gt=0,
        description='Produce this many units. One unit answers per-unit figures.',
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> CostBreakdownResponse:
    """Per-ingredient cost estimate (layer-average rates).

    Default answers one unit by the template's default formula. A caller
    that shows a specific recipe asks with ``recipe_id`` — and for a batch
    figure passes ``qty`` explicitly rather than dividing a per-unit
    answer a second time.
    """
    exists = await core_api.product_templates.exists_for_org_async(
        db, org_id, template_id
    )
    if not exists:
        raise NotFoundException('template', get_current_lang())
    return await cost_breakdown.compute_breakdown(
        db, org_id, template_id, qty, recipe_id=recipe_id
    )


@router.get(
    '/tree/{template_id}',
    response_model=BomTreeResponse,
)
async def get_bom_tree(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BomTreeResponse:
    """Full recursive BOM tree under a parent template (for BomTreeEditor)."""
    tree = await bom_tree.get_tree(db, org_id, template_id)
    tree_lines: list[BoMLine] = []
    _collect_tree_lines(tree, tree_lines)
    await _attach_child_names(db, org_id, tree_lines)
    root_node = BomTreeNode.model_validate(tree)
    return BomTreeResponse(
        parent_template_id=template_id,
        root=root_node,
    )


@router.post(
    '/{line_id}/move',
    response_model=BoMLineRead,
    dependencies=[require_permission('maker:manage')],
)
async def move_bom_line(
    line_id: UUID,
    data: BomMoveRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BoMLineRead:
    """Reparent an existing line under a new parent; cycle + UNIQUE-validated."""
    line = await bom_tree.move_line(
        db, org_id, line_id, data.new_parent_template_id, current_user
    )
    await db.refresh(line)
    return BoMLineRead.model_validate(line)


@router.delete(
    '/{line_id}',
    status_code=204,
    dependencies=[require_permission('maker:manage')],
)
async def remove_bom_line(
    line_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    # The tree view names a line without its recipe; the recipe-scoped delete
    # is the one path that validates and journals the removal.
    recipe_id = await db.scalar(
        select(BoMLine.recipe_id).where(
            BoMLine.id == line_id, BoMLine.organization_id == org_id
        )
    )
    if recipe_id is None:
        raise NotFoundException('bom_line', get_current_lang())
    await recipe_service.delete_bom_line(db, org_id, recipe_id, line_id, current_user)
