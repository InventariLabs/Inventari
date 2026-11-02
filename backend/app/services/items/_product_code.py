"""Which carrier keeps a product code — the record, or its catalogue row.

One question, asked by every door that creates a record: the scan, the
quick-add form, and the resolver that mints a catalogue row for a product
nobody entered yet. It used to be answered in two copies, and a rule added
to one of them was a rule the other door did not have.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.services.items._module_owner import resolve_module_owner


def code_belongs_to_the_record(
    item_data: dict[str, Any],
    *,
    card_named: bool = False,
) -> bool:
    """Whether the payload's code describes *this record* rather than its card.

    Two things in a create payload say so, and both are the payload already
    naming what the record is. A card the caller pinned by ``template_id``
    was identified before the code arrived, so the code cannot be what chose
    it — it says nothing about the product. A ``meta_data`` namespace a
    vertical module claims makes the record a *unit* of something, and a code
    on a unit is that unit's own tag: the asset tag of one laptop, not the
    number of the model the fleet buys.

    What is left is the core stock record created without a card pinned to
    it, which still offers its code to the catalogue row — the scan and the
    quick-add form, where the code is a product's EAN.
    """
    if card_named:
        return True
    return resolve_module_owner(item_data.get('meta_data')) is not None


async def live_record_wearing_async(
    db: AsyncSession,
    org_id: UUID,
    barcode: str,
) -> Item | None:
    """The live record that already wears *barcode*, if there is one.

    Records made before the code moved to the catalogue keep it on the row,
    which is the state of every existing installation — so this is not an
    edge case, it is what most databases look like.
    """
    return await db.scalar(
        select(Item).where(
            Item.organization_id == org_id,
            Item.barcode == barcode,
            Item.is_deleted.is_(False),
        )
    )


async def place_product_code_async(
    db: AsyncSession,
    org_id: UUID,
    item_data: dict[str, Any],
    template: ProductTemplate,
    *,
    card_named: bool = False,
) -> None:
    """Decide which carrier keeps a scanned code, for every door that creates.

    A code that arrived from a scan is the *product's* code: the template
    matched by it — or minted carrying it — is where receipts write it and
    where a scan reads it. Copying it onto the record as well made the
    second record of the same product a blind refusal on
    ``uq_items_org_barcode_active`` (the form has no code field to recover
    with), so the record stays bare whenever the catalogue row holds the
    code. Only a template matched by name while carrying a *different* code
    leaves the scanned one on the record — the one-off case the column's
    own docstring keeps it for.

    That is the rule for a product's code. The code the payload may be
    carrying about a *unit* instead never leaves the record:
    :func:`code_belongs_to_the_record` decides, and ``card_named`` is how
    this caller says it named the card itself. The card wearing the very
    same code is the one case that still pops it — a code keeps one carrier,
    and the card got there first.

    A code already worn by a live record of a *different* product is not
    written onto this template at all. Scanning such a code under a changed
    name used to mint a second carrier, and from then on the scan answered
    with the new product while the older record — holding the same code —
    dropped out of the answer entirely. The code stays where it is and the
    refusal below names it, exactly as the manual form answers the same
    collision. A record of the *same* product is no conflict: that is the
    code moving to where it belongs.
    """
    scanned_barcode = item_data.get('barcode')
    if not scanned_barcode:
        return

    rides_with_the_record = code_belongs_to_the_record(item_data, card_named=card_named)

    if template.barcode == scanned_barcode:
        item_data.pop('barcode')
    elif (
        not rides_with_the_record
        and template.organization_id == org_id
        and not template.barcode
    ):
        if not await _code_worn_by_another_product_async(
            db, org_id, scanned_barcode, template.id
        ):
            template.barcode = scanned_barcode
            db.add(template)
            item_data.pop('barcode')

    if item_data.get('barcode'):
        # The one-off case is the only one that can collide on the record
        # level; the refusal runs after the resolver, so nothing was minted
        # for a request that ends here.
        from ._create import _ensure_barcode_unique_async

        await _ensure_barcode_unique_async(db, org_id, item_data['barcode'])


async def place_edited_product_code_async(
    db: AsyncSession,
    org_id: UUID,
    item: Item,
    update_data: dict[str, Any],
) -> dict[str, tuple[Any, Any]]:
    """The edit form's door to :func:`place_product_code_async`.

    A receiving or picking scan reads the catalogue row and nothing else, so
    a code typed into the form for a record that has one is the product's
    code: it goes to the row when the row has none, and the row's own code
    sent back unchanged — the form posts its whole state — is no change at
    all, rather than a copy on the record the next record would collide
    with. A code another product's row already carries is refused with the
    sentence every door uses. What stays on the record is what stayed there
    before: the unit tag of a module-owned record, and a code that differs
    from the one the row already has.

    An emptied field says the same thing in the other direction. The form
    shows the record's code or, failing that, its product's, so clearing it
    clears the product's code as well — left on the row, the save reported
    success and the page showed the old code again. A module-owned record
    is the exception: what it wears is its unit's tag, and emptying that
    must not take the product's code from the catalogue.

    Returns the row's change, for the audit entry the record's edit writes.
    """
    if 'barcode' not in update_data or item.template_id is None:
        return {}
    code = update_data['barcode']
    if not code:
        return await _clear_product_code_async(db, org_id, item)
    if code == item.barcode:
        return {}
    template = await db.get(ProductTemplate, item.template_id)
    if template is None:
        return {}
    if template.barcode == code:
        update_data.pop('barcode')
        return {}

    taken = await db.scalar(
        select(ProductTemplate.id).where(
            ProductTemplate.organization_id == org_id,
            ProductTemplate.barcode == code,
            ProductTemplate.id != template.id,
        )
    )
    if taken is not None:
        from ._create import refuse_taken_barcode

        refuse_taken_barcode(code)

    if (
        resolve_module_owner(item.meta_data) is not None
        or template.organization_id != org_id
        or template.barcode
    ):
        return {}
    template.barcode = code
    db.add(template)
    update_data.pop('barcode')
    return {'barcode': (None, code)}


async def _clear_product_code_async(
    db: AsyncSession,
    org_id: UUID,
    item: Item,
) -> dict[str, tuple[Any, Any]]:
    """Take the code off the record's own catalogue row, when it is the org's."""
    if resolve_module_owner(item.meta_data) is not None:
        return {}
    template = await db.get(ProductTemplate, item.template_id)
    if template is None or template.organization_id != org_id or not template.barcode:
        return {}
    was, template.barcode = template.barcode, None
    db.add(template)
    return {'barcode': (was, None)}


async def _code_worn_by_another_product_async(
    db: AsyncSession,
    org_id: UUID,
    barcode: str,
    template_id: UUID,
) -> bool:
    """True when a live record of a different product already wears *barcode*."""
    carrier = await live_record_wearing_async(db, org_id, barcode)
    return carrier is not None and carrier.template_id != template_id
