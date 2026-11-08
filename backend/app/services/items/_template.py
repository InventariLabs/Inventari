"""Product template resolution and updates.

Every path that creates an item resolves its template here. Keeping a second
copy of this logic is how items created by a scan ended up without one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.db_utils import get_org_owned_or_404
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.money import quantise
from app.core.product_template_metadata import set_template_nutrition
from app.i18n.service import get_current_lang
from app.models.category import Category
from app.models.product_template import ProductTemplate
from app.schemas.item import ItemCreate
from app.services.items.nutrition import extract_nutrition_info_from_off_metadata


async def resolve_template_by_id_async(
    db: AsyncSession,
    template_id: UUID,
    org_id: UUID,
) -> ProductTemplate:
    """The card the caller named — this organization's, or a shared one.

    A caller that passes ``template_id`` is pointing at a card, so no
    barcode or name matching runs: two cards of one name must not pull the
    record onto the wrong one. An unknown id and another organization's
    card are the same refusal — 404, not 403, which would confirm the row
    exists.
    """
    template = await db.get(ProductTemplate, template_id)
    if template is None or template.organization_id not in (None, org_id):
        raise NotFoundException('template', get_current_lang())
    return template


def _write_card_product_fields(
    db: AsyncSession,
    template: ProductTemplate,
    item_data: dict[str, Any],
    org_id: UUID,
) -> None:
    """The payload's product-level fields, written to the card the record joins.

    One writer for both doors — the card the caller *named* and the card the
    resolver *matched* — because a payload naming a threshold or a unit weight
    means the same thing whichever way the record arrived at its card.

    Only ever an organization's own card: a shared one (``organization_id IS
    NULL``) is shared by everybody, and changing its threshold or unit weight
    would change them for everybody. A removal strategy or a unit weight the
    shared card does not already read is refused rather than dropped
    (:func:`refuse_a_shared_strategy_change`, :func:`refuse_a_shared_weight_
    change`).
    """
    if template.organization_id != org_id:
        if 'removal_strategy' in item_data:
            refuse_a_shared_strategy_change(
                template.removal_strategy, item_data['removal_strategy']
            )
        if item_data.get('weight_value') is not None:
            refuse_a_shared_weight_change(
                template, item_data['weight_value'], item_data.get('weight_uom_id')
            )
        return
    if item_data.get('min_quantity') is not None:
        template.min_quantity = float(item_data.get('min_quantity') or 0)
        db.add(template)
    if item_data.get('weight_value') is not None:
        template.weight_value = Decimal(str(item_data['weight_value']))
        template.weight_uom_id = item_data.get('weight_uom_id')
        db.add(template)
    if item_data.get('removal_strategy') is not None:
        template.removal_strategy = item_data['removal_strategy']
        db.add(template)


async def refuse_sku_in_use_async(
    db: AsyncSession,
    org_id: UUID,
    sku: str,
    *,
    except_template_id: UUID | None = None,
) -> None:
    """Refuse a SKU another product of the organization already carries.

    ``uq_templates_org_sku`` keeps a SKU unique per organization; asked in
    advance, the collision is a refusal that names the SKU rather than the
    constraint's own error.
    """
    stmt = select(ProductTemplate.id).where(
        ProductTemplate.organization_id == org_id, ProductTemplate.sku == sku
    )
    if except_template_id is not None:
        stmt = stmt.where(ProductTemplate.id != except_template_id)
    if await db.scalar(stmt.limit(1)) is not None:
        raise ServiceRejectionError('sku_in_use', sku=sku)


async def _write_card_sku_async(
    db: AsyncSession,
    template: ProductTemplate,
    item_data: dict[str, Any],
    org_id: UUID,
) -> None:
    """The payload's SKU, written to the card the record joins.

    Only an organization's own card takes it, and only when it differs: a
    shared card's SKU is every organization's, the same reason its threshold
    is not written. A payload that names no SKU leaves the card's as it is.
    """
    sku = item_data.get('sku')
    if not sku or template.organization_id != org_id or template.sku == sku:
        return
    await refuse_sku_in_use_async(db, org_id, sku, except_template_id=template.id)
    template.sku = sku
    db.add(template)


def refuse_a_shared_strategy_change(current: str | None, requested: str | None) -> None:
    """Refuse a removal strategy a shared product does not already read.

    The order stock leaves in is the product's, and a shared product is every
    organization's, so one of them cannot reorder it for all. Dropping the
    choice the way a threshold is dropped answered "Updated" while dispatches
    went on drawing FIFO. The strategy the product already reads — unset is
    FIFO — is no change: the form posts its whole state.
    """
    if (requested or 'FIFO') != (current or 'FIFO'):
        raise ServiceRejectionError('removal_strategy_of_shared_product')


def refuse_a_shared_weight_change(
    card: ProductTemplate, weight_value: Any, weight_uom_id: UUID | None
) -> None:
    """Refuse a unit weight a shared product does not already record.

    The weight of one piece is the product's (ADR-015), and a shared product
    is every organization's, so it is never written for one of them. Dropping
    the weight answered "Updated" while the card — and every line weight read
    from it — kept the old one. The weight the card already records is no
    change: the form posts its whole state, and a weight sent without a unit
    is read in the card's own.
    """

    def measure(value: Any, uom_id: UUID | None) -> tuple[Decimal, UUID | None] | None:
        if value is None:
            return None
        return quantise(Decimal(str(value)), 6), uom_id

    requested = measure(weight_value, weight_uom_id or card.weight_uom_id)
    if requested != measure(card.weight_value, card.weight_uom_id):
        raise ServiceRejectionError('unit_weight_of_shared_product')


async def resolve_template_for_create_async(
    db: AsyncSession,
    item_in: ItemCreate,
    item_data: dict[str, Any],
    org_id: UUID,
) -> tuple[ProductTemplate, bool]:
    """The card a new record joins: the one the caller named, else the match.

    A named card binds the record directly — barcode and name matching do
    not run, so two cards of one name cannot answer instead (:func:`resolve_
    template_by_id_async` holds the visibility rule and its refusal).
    Without a named card the resolver matches, and the card it chose is
    written back onto the payload.
    """
    if item_in.template_id is not None:
        template = await resolve_template_by_id_async(db, item_in.template_id, org_id)
        # The named card takes the payload's product-level fields exactly as
        # the matched one does below — one writer, two doors, one answer.
        _write_card_product_fields(db, template, item_data, org_id)
        await _write_card_sku_async(db, template, item_data, org_id)
        return template, False
    template, template_created = await resolve_template_default_async(
        db, item_data, org_id
    )
    if not template_created:
        await _write_card_sku_async(db, template, item_data, org_id)
    item_data['template_id'] = template.id
    return template, template_created


async def find_template_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    name: str | None = None,
    barcode: str | None = None,
    brand: str | None = None,
) -> ProductTemplate | None:
    """The template these fields match — the same matching the create path does.

    One function, so a reader asking "which catalogue row would this record
    land on" gets the same answer as the write that mints the record. A
    second copy of the matching is how the form's hint and the unit the row
    actually landed with came to disagree.
    """
    template = None
    if barcode:
        stmt = (
            select(ProductTemplate)
            .where(
                (ProductTemplate.organization_id == org_id)
                | (ProductTemplate.organization_id.is_(None)),
                ProductTemplate.barcode == barcode,
            )
            .order_by(ProductTemplate.organization_id.desc().nullslast())
        )
        result = await db.execute(stmt)
        template = result.scalars().first()

    if not template and name:
        stmt = select(ProductTemplate).where(
            (ProductTemplate.organization_id == org_id)
            | (ProductTemplate.organization_id.is_(None)),
            ProductTemplate.name == name,
        )
        if brand:
            stmt = stmt.where(ProductTemplate.brand == brand)
        stmt = stmt.order_by(ProductTemplate.organization_id.desc().nullslast())
        result = await db.execute(stmt)
        template = result.scalars().first()

    return template


async def _category_default_strategy_async(
    db: AsyncSession, category_id: UUID | None
) -> str | None:
    """The removal strategy a product minted under *category_id* starts with.

    Read here, where every door mints its card, so a scan, an import and the
    add form give a new product the same strategy. The caller has already
    checked the category belongs to the organization.
    """
    if category_id is None:
        return None
    category = await db.get(Category, category_id)
    return category.default_removal_strategy if category is not None else None


async def resolve_template_default_async(
    db: AsyncSession,
    item_data: dict[str, Any],
    org_id: UUID,
) -> tuple[ProductTemplate, bool]:
    """Find the template this item belongs to, creating one if none matches.

    Matching goes by barcode first, then by name (and brand, when given),
    preferring the organization's own template over a shared one. The
    second return value says whether the template was minted by this call:
    a caller that fills in a unit after the fact may only write it on a
    template it just created — an older record, and a shared one above
    all, keeps whatever history gave it.
    """
    from app.services.sku_service import SkuService

    barcode = item_data.get('barcode')
    name = item_data.get('name')
    brand = item_data.get('brand')

    template = await find_template_async(
        db, org_id, name=name, barcode=barcode, brand=brand
    )

    if not template:
        # A code worn by a live record does not ride into a freshly minted
        # catalogue row. Records made before the code moved to the product
        # keep it on the row — the state of every existing installation —
        # and minting a second carrier is how the older record dropped out
        # of the scan's answer. Neither does a code the payload is carrying
        # about this record rather than about a product: a unit's own tag
        # has no business becoming the catalogue row's name-in-code.
        # The placement rule downstream decides what happens to the code
        # itself; here it simply is not copied.
        minted_barcode = barcode
        if barcode and org_id is not None:
            from ._product_code import (
                code_belongs_to_the_record,
                live_record_wearing_async,
            )

            if code_belongs_to_the_record(item_data) or await live_record_wearing_async(
                db, org_id, barcode
            ):
                minted_barcode = None
        template = ProductTemplate(
            organization_id=org_id,
            name=name,
            brand=brand,
            barcode=minted_barcode,
            uom_id=item_data.get('uom_id'),
            weight_value=item_data.get('weight_value'),
            weight_uom_id=item_data.get('weight_uom_id'),
            volume_value=item_data.get('volume_value'),
            volume_uom_id=item_data.get('volume_uom_id'),
            description=item_data.get('description'),
            image_url=item_data.get('image_url'),
            min_quantity=item_data.get('min_quantity', 0.0),
            removal_strategy=item_data.get('removal_strategy')
            or await _category_default_strategy_async(db, item_data.get('category_id')),
        )
        named_sku = item_data.get('sku')
        if named_sku and org_id is not None:
            await refuse_sku_in_use_async(db, org_id, named_sku)
            template.sku = named_sku
        else:
            auto_sku = (
                await SkuService.generate_next_async(db, org_id)
                if org_id is not None
                else None
            )
            if auto_sku:
                template.sku = auto_sku
        nutrition = extract_nutrition_info_from_off_metadata(
            item_data.get('meta_data') or {}
        )
        if nutrition:
            set_template_nutrition(template, nutrition)
        # A savepoint, because two requests that met the same new code both
        # looked, found nothing and wrote: the second hits the organization's
        # unique code. It joins the card the first one committed rather than
        # answering 500, exactly as a request arriving a moment later would.
        try:
            async with db.begin_nested():
                db.add(template)
                await db.flush()
        except IntegrityError as exc:
            if minted_barcode is None or 'uq_templates_org_barcode' not in str(
                exc.orig
            ):
                raise
            template = await find_template_async(
                db, org_id, name=name, barcode=barcode, brand=brand
            )
            if template is None:
                raise
            _write_card_product_fields(db, template, item_data, org_id)
            return template, False
        return template, True
    _write_card_product_fields(db, template, item_data, org_id)

    return template, False


def update_product_template_nutrition(
    db: Session,
    template_id: UUID,
    org_id: UUID,
    nutrition_info: dict | None,
) -> ProductTemplate:
    """Update nutrition_info on a ProductTemplate scoped to the organization."""

    template = get_org_owned_or_404(
        db,
        ProductTemplate,
        template_id,
        org_id,
        resource='template',
        lang=get_current_lang(),
    )

    set_template_nutrition(template, nutrition_info)
    db.flush()
    db.refresh(template)
    return template
