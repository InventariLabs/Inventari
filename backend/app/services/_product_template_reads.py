"""Read-only ProductTemplate lookups.

Extracted from ``product_template_service.py`` — read operations on
ProductTemplate (list, get, exists, lookup by barcode / recipe usage).
Kept separate from writes so the public API can depend on this file
without pulling in the heavier write-side code paths.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import in_ids
from app.core.label_codes import LABEL_CODE_PATTERN
from app.core.read_scope import keep_loaded
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.product_template import ProductTemplate
from app.models.uom import Uom


async def list_templates_for_org_async(
    db: AsyncSession,
    org_id: UUID,
    limit: int = 200,
) -> list[ProductTemplate]:
    result = await db.scalars(
        select(ProductTemplate)
        .where(
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            )
        )
        .order_by(ProductTemplate.name)
        .limit(limit)
    )
    return list(result.all())


async def count_templates_for_org_async(db: AsyncSession, org_id: UUID) -> int:
    """Count the templates an org can pick from (org-scoped + global rows).

       Same visibility set as :func:`list_templates_for_org_async` — the
    "is the catalog empty" question for form gates must answer
       what the picker would actually offer.
    """
    return (
        await db.scalar(
            select(func.count(ProductTemplate.id)).where(
                or_(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.organization_id.is_(None),
                )
            )
        )
        or 0
    )


async def list_templates_by_ids_async(
    db: AsyncSession,
    org_id: UUID,
    template_ids: list[UUID],
) -> list[ProductTemplate]:
    """Load several templates at once, scoped to org + global rows.

    The batch twin of ``get_template_for_org_async``. Availability checks
    resolve many templates per request and reading them one at a time turns
    a list of recipes into a query per ingredient.

    The ids travel as one array, not one bind parameter each: a report over a
    warehouse names every product it holds, and past 32 767 parameters the
    driver refuses the statement.
    """
    if not template_ids:
        return []
    result = await db.scalars(
        select(ProductTemplate).where(
            in_ids(ProductTemplate.id, template_ids),
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
        )
    )
    templates = list(result.all())
    keep_loaded(db, templates)
    return templates


async def names_and_units_by_ids_async(
    db: AsyncSession,
    org_id: UUID,
    template_ids: Iterable[UUID],
) -> dict[UUID, tuple[str, str | None]]:
    """Each template's name and its unit's symbol, in one narrow read.

    A report that prints a product beside a stored id needs these two
    columns and nothing else. Loading whole templates for them — the unit
    relationships with them — cost about a second for the products of one
    zone at a hundred thousand products. Same visibility as
    :func:`list_templates_by_ids_async`: the organization's own and the
    global rows; an id outside them is absent.
    """
    ids = list(dict.fromkeys(template_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(ProductTemplate.id, ProductTemplate.name, Uom.symbol)
        .outerjoin(Uom, Uom.id == ProductTemplate.uom_id)
        .where(
            in_ids(ProductTemplate.id, ids),
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
        )
    )
    return {tid: (name, symbol) for tid, name, symbol in rows.all()}


async def list_templates_for_org_with_recipe_usage_async(
    db: AsyncSession,
    org_id: UUID,
    limit: int = 200,
) -> list[ProductTemplate]:
    """List org + global templates ordered by recipe-ingredient usage.

    Templates referenced by this org's recipe ingredients surface first
    (the most likely relevant matches for LLM-prompt catalog dumps),
    then alphabetical. Tier 2 CoreAPI extension for the recipes
    ``template_matcher`` LLM-prompt builder.

    The usage count comes from the recipes module's own ``RecipeIngredient``
    table, so the ordering is supplied by that module through
    ``app.core.template_ranking``. Without it, falls back to alphabetical.
    """
    from app.core.template_ranking import rank_templates_by_usage

    ranked = await rank_templates_by_usage(db, org_id, limit)
    if ranked is not None:
        return ranked
    # No recipes module: usage counts do not exist, so plain alphabetical
    # ordering is the honest answer rather than an error.
    return await list_templates_for_org_async(db, org_id, limit=limit)


async def get_template_for_org_async(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> ProductTemplate | None:
    tpl = await db.get(ProductTemplate, template_id)
    if tpl is None:
        return None
    if tpl.organization_id is not None and tpl.organization_id != org_id:
        return None
    return tpl


async def template_exists_for_org_async(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> bool:
    """Async: check whether a template exists and is visible to *org_id*."""
    result = await db.scalar(
        select(ProductTemplate.id).where(
            ProductTemplate.id == template_id,
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
        )
    )
    return result is not None


def template_by_code_query(org_id: UUID, code: str) -> Select[tuple[ProductTemplate]]:
    """The catalogue rows a scanned code can name: by barcode, else by SKU.

    A small warehouse prints its own labels from the SKU, and a supplier's
    alphanumeric code lives in the barcode column, so both are the same
    question. A row whose barcode is the code comes before one whose SKU is
    (``uq_templates_org_sku`` keeps a SKU unique per organization, but a
    shipped template may be global), and the organization's own row before a
    global one.
    """
    return (
        select(ProductTemplate)
        .where(
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
            or_(ProductTemplate.barcode == code, ProductTemplate.sku == code),
        )
        .order_by(
            func.coalesce(ProductTemplate.barcode, '') != code,
            ProductTemplate.organization_id.is_(None),
        )
    )


async def get_template_by_barcode_async(
    db: AsyncSession, org_id: UUID, barcode: str
) -> ProductTemplate | None:
    """Async: the template a scanned code names, scoped to org + global templates.

    The one lookup behind the scan pages and the picking and receiving
    sessions, so it answers in the order the scan registry does. The code is
    whatever the scanner read, so a scan address is unwrapped first; the text
    of a printed pool label then comes before any product identity (it names
    the template of the record it is stuck to), then the catalogue by barcode
    or SKU, and last the barcode of a stock record, which names its template.
    """
    from app.core.scan_registry import extract_scan_code

    code = extract_scan_code(barcode)
    if LABEL_CODE_PATTERN.match(code):
        labelled = await db.scalar(
            select(ProductTemplate)
            .join(Item, Item.template_id == ProductTemplate.id)
            .join(LabelPool, LabelPool.item_id == Item.id)
            .where(
                LabelPool.short_code == code,
                LabelPool.organization_id == org_id,
                Item.organization_id == org_id,
            )
        )
        if labelled is not None:
            return labelled
    template = await db.scalar(template_by_code_query(org_id, code))
    if template is not None:
        return template
    return await db.scalar(
        select(ProductTemplate)
        .join(Item, Item.template_id == ProductTemplate.id)
        .where(
            Item.barcode == code,
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
        )
        .order_by(Item.created_at.desc())
    )
