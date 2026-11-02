"""Write operations on ProductTemplate: create, update, delete, clone.

Extracted from ``product_template_service.py`` — write-side operations.
Kept separate from reads so callers that only need lookups (e.g. the
catalog browsing endpoint) can depend on the lighter ``_product_template_reads``
module.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ServiceRejectionError
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.services.audit_service import audit_key, audit_value, log_action_async
from app.services.sku_service import SkuService

#: What a template is, as far as the journal is concerned. Not every column:
#: a template carries ids for units and images that say nothing to a reader,
#: and the fields below are the ones a change to which changes the meaning of
#: every record written against it.
_AUDITED = (
    'name',
    'brand',
    'barcode',
    'sku',
    'description',
    'uom_id',
    'weight_value',
    'volume_value',
    'min_quantity',
    'removal_strategy',
    'meta_data',
)


def _template_snapshot(tpl: ProductTemplate) -> dict:
    return {field: audit_value(getattr(tpl, field, None)) for field in _AUDITED}


async def _uom_word_async(db: AsyncSession, uom_id: UUID | None) -> str | None:
    """The reader-facing word for a unit, read while the row is in hand.

    The symbol (`kg`), not the catalogue name (`Kilogram`): the symbol is
    what the product screen and the shelf label print — the same rule the
    item writer's reference naming applies. None when the template carries
    no unit or the row has since left the catalogue.
    """
    if uom_id is None:
        return None
    uom = await db.get(Uom, uom_id)
    return uom.symbol if uom is not None else None


async def _journal_record_async(db: AsyncSession, tpl: ProductTemplate) -> dict:
    """The full snapshot, with every reference the writer can name named.

    Journal entries have two layers to say in the reader's language — the
    field name and the value — and a value that is an identifier is not
    said at all: `uom_id` alone reached the page as a uuid, which is how a
    Polish row came to read `Jednostka: 16282d80`. The name travels beside
    the id (`uom_name`), the shape the journal reader already prints on the
    id's own line instead of as a field of its own.

    The class, and where it stands after this: every snapshot field that is
    a reference with a readable name is named at write time — items name
    their location, category, template and unit (`_reference_names`),
    storages name their parent and type, roles carry `role_name`, a
    template names its unit, and equipment's maintenance rows name the
    asset beside the reference id (`item_name`). What stays unnamed is the
    id whose referent the writer does not hold (a profile is written by its
    key, which is its name) and every entry written before this change: the
    journal is immutable, so old rows keep the ids they were written with.
    """
    snapshot = _template_snapshot(tpl)
    word = await _uom_word_async(db, tpl.uom_id)
    if word is not None:
        snapshot['uom_name'] = word
    return snapshot


async def _log_template_async(
    db: AsyncSession,
    tpl: ProductTemplate,
    *,
    org_id: UUID,
    user_id: UUID | None,
    action: AuditAction,
    snapshot: dict | None = None,
) -> None:
    """Record a write to a product template.

    A template is the definition every record is written against: change the
    unit of measure on one and every quantity stored for its products means
    something else. The rule names the catalogue among the four kinds of act
    the journal holds, and this was the one catalogue table nothing recorded.

    Here rather than in the modules that call it, for the reason the document
    templates were moved here: equipment models *are* product templates, and
    the same row must not be in the journal when equipment wrote it and
    missing when the products screen did.
    """
    await log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.PRODUCT_TEMPLATE,
        target_id=tpl.id,
        snapshot=snapshot
        if snapshot is not None
        else await _journal_record_async(db, tpl),
    )


async def _generate_sku_async(
    db: AsyncSession, org_id: UUID, prefix: str = 'STM-'
) -> str:
    """Generate the org's next SKU, falling back to a random code.

    Single fallback path — the three call sites previously used two
    different prefixes (STB-/STM-) depending on which copy they hit.
    """
    sku = await SkuService.generate_next_async(db, org_id)
    if sku:
        return sku
    return f'{prefix}{str(uuid.uuid4())[:8].upper()}'


async def _flush_new_template_async(
    db: AsyncSession, tpl: ProductTemplate, barcode: str | None
) -> None:
    """Write a new card, answering a lost race for its code as a refusal.

    Two requests that met the same new code both looked, found nothing and
    wrote: the second hits the organization's unique code. The savepoint
    keeps the surrounding transaction usable, and the answer is the one a
    request arriving a moment later gets from the look — not a 500.
    """
    try:
        async with db.begin_nested():
            db.add(tpl)
            await db.flush()
    except IntegrityError as exc:
        if barcode and 'uq_templates_org_barcode' in str(exc.orig):
            raise ServiceRejectionError(
                'barcode_already_exists', barcode=barcode
            ) from exc
        raise


async def create_stub_template_async(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    barcode: str | None = None,
    user_id: UUID | None = None,
) -> ProductTemplate:
    """Async: create a minimal stub ProductTemplate for quick entry."""
    if barcode:
        existing = await db.scalar(
            select(ProductTemplate).where(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.barcode == barcode,
            )
        )
        if existing:
            raise ServiceRejectionError('barcode_already_exists', barcode=barcode)

    sku = await _generate_sku_async(db, org_id)

    # Same as the full create path: a stub is a catalogue row the unit
    # guard and the stock screen read, and "pieces" is the answer for a
    # product nobody described yet.
    from app.services.items._create import _default_piece_uom_id_async

    resolved_uom_id = await _default_piece_uom_id_async(db, org_id)

    meta_data: dict = {'is_stub': True}

    tpl = ProductTemplate(
        organization_id=org_id,
        name=name,
        barcode=barcode,
        sku=sku,
        meta_data=meta_data,
        uom_id=resolved_uom_id,
    )
    await _flush_new_template_async(db, tpl, barcode)
    await _log_template_async(
        db,
        tpl,
        org_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        snapshot={**(await _journal_record_async(db, tpl)), 'stub': True},
    )
    return tpl


async def clone_template(
    db: AsyncSession,
    original_id: UUID,
    new_name: str,
    new_barcode: str | None,
    organization_id: UUID,
    user_id: UUID | None = None,
) -> object:
    """Clone a product template with a new name and optional barcode."""
    original = await db.get(ProductTemplate, original_id)
    if not original:
        raise ServiceRejectionError('product_template_not_found')

    if (
        original.organization_id != organization_id
        and original.organization_id is not None
    ):
        raise ServiceRejectionError('template_other_organization')

    new_sku = await _generate_sku_async(db, organization_id)

    cloned = ProductTemplate(
        # Assign the cloned template to the caller's org, not the
        # original's. Cloning a system/global template previously copied the
        # original (None) org_id, flooding the global catalog with org-specific
        # clones instead of scoping them to the requesting organization.
        organization_id=organization_id,
        name=new_name,
        brand=original.brand,
        barcode=new_barcode,
        sku=new_sku,
        uom_id=original.uom_id,
        weight_value=original.weight_value,
        weight_uom_id=original.weight_uom_id,
        volume_value=original.volume_value,
        volume_uom_id=original.volume_uom_id,
        image_url=original.image_url,
        description=original.description,
        min_quantity=original.min_quantity,
        meta_data=original.meta_data,
    )
    db.add(cloned)
    await db.flush()
    await db.refresh(cloned)
    await _log_template_async(
        db,
        cloned,
        org_id=organization_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        snapshot={
            **(await _journal_record_async(db, cloned)),
            'copied_from': original.name,
        },
    )
    return cloned


async def create_product_template_async(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    brand: str | None = None,
    barcode: str | None = None,
    sku: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    meta_data: dict | None = None,
    uom_id: UUID | None = None,
    weight_value: float | None = None,
    weight_uom_id: UUID | None = None,
    volume_value: float | None = None,
    volume_uom_id: UUID | None = None,
    min_quantity: float | None = None,
    user_id: UUID | None = None,
) -> object:
    if not sku:
        sku = await _generate_sku_async(db, org_id)

    if uom_id is None:
        # The template is the row the rest of the app reads — the BoM
        # convertibility guard and the stock screen both take the unit
        # from it — so a template born without one silences the guard and
        # blanks the screen. Pieces, the same answer the record path
        # gives; an explicitly chosen unit still wins.
        from app.services.items._create import _default_piece_uom_id_async

        uom_id = await _default_piece_uom_id_async(db, org_id)

    tpl = ProductTemplate(
        organization_id=org_id,
        name=name,
        brand=brand,
        barcode=barcode,
        sku=sku,
        description=description,
        image_url=image_url,
        meta_data=meta_data,
        uom_id=uom_id,
        weight_value=weight_value,
        weight_uom_id=weight_uom_id,
        volume_value=volume_value,
        volume_uom_id=volume_uom_id,
        min_quantity=min_quantity,
    )
    await _flush_new_template_async(db, tpl, barcode)
    await db.refresh(tpl)
    await _log_template_async(
        db, tpl, org_id=org_id, user_id=user_id, action=AuditAction.CREATE
    )
    return tpl


async def update_product_template_async(
    db: AsyncSession,
    template_id: UUID,
    org_id: UUID,
    name: str | None = None,
    brand: str | None = None,
    barcode: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    meta_data: dict | None = None,
    user_id: UUID | None = None,
) -> object:
    tpl = await db.get(ProductTemplate, template_id)
    if not tpl:
        raise ServiceRejectionError('product_template_not_found')
    if tpl.organization_id != org_id and tpl.organization_id is not None:
        raise ServiceRejectionError('template_other_organization')

    before = {field: getattr(tpl, field, None) for field in _AUDITED}

    if name is not None:
        tpl.name = name
    if brand is not None:
        tpl.brand = brand
    if barcode is not None:
        tpl.barcode = barcode
    if description is not None:
        tpl.description = description
    if image_url is not None:
        tpl.image_url = image_url
    if meta_data is not None:
        tpl.meta_data = meta_data

    await db.flush()
    await db.refresh(tpl)
    # A submit that changed nothing is not a change. The form posts its whole
    # state, so without this the journal would gain a row every time somebody
    # opened a template and pressed save.
    moved = [
        field
        for field in _AUDITED
        if audit_key(before[field]) != audit_key(getattr(tpl, field, None))
    ]
    if moved:
        await _log_template_async(
            db,
            tpl,
            org_id=org_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            snapshot={
                'name': tpl.name,
                'before': {f: audit_value(before[f]) for f in moved},
                'after': {f: audit_value(getattr(tpl, f, None)) for f in moved},
            },
        )
    return tpl


async def delete_product_template_async(
    db: AsyncSession,
    template_id: UUID,
    org_id: UUID,
    user_id: UUID | None = None,
) -> None:
    tpl = await db.get(ProductTemplate, template_id)
    if not tpl:
        raise ServiceRejectionError('product_template_not_found')
    if tpl.organization_id != org_id and tpl.organization_id is not None:
        raise ServiceRejectionError('template_other_organization')

    # Refuse to delete a template still referenced by items. Deleting it
    # anyway would raise an unhandled IntegrityError (HTTP 500) on the
    # items.template_id FK; surface a clear business error instead.
    items_count = await db.scalar(
        select(func.count(Item.id)).where(
            Item.template_id == tpl.id,
            Item.is_deleted.is_(False),
        )
    )
    if items_count:
        raise ServiceRejectionError('template_in_use_by_items', count=items_count)

    # Before the row goes, while there is still a definition to describe.
    await _log_template_async(
        db, tpl, org_id=org_id, user_id=user_id, action=AuditAction.HARD_DELETE
    )
    await db.delete(tpl)
    await db.flush()
