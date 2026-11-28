"""Which product an import row is about.

A sheet names a product by its SKU, by a barcode, by its name, or — the way
Odoo's stock export writes it — as "[REF] Name". A row of a sheet that
carries no stock adds the product alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import sku_from_cell
from app.models.product_template import ProductTemplate
from app.services._product_template_writes import (
    PLACEHOLDER_SKU_PREFIX,
    create_product_template_async,
)
from app.services.sku_service import SkuService

from ._product_code import live_record_wearing_async
from ._template import find_template_async

#: "[CHE-001] Cheese": the reference in brackets, then the product's name.
_REFERENCE = re.compile(r'^\[([^\[\]]+)\]\s*(\S.*)$')


async def read_reference(
    db: AsyncSession, org_id: UUID, name: str, column: str
) -> tuple[str, str | None]:
    """The name and the SKU a name cell holds when it reads "[REF] Name".

    The brackets are a reference only when a product already carries it as its
    SKU: a reading the reader can see in the catalogue. "[2 pcs] Batteries"
    and "[A4] Paper" are the names their sheet gives them, unless the
    organization has a product with that very code.
    """
    match = _REFERENCE.match(name)
    if match is None:
        return name, None
    reference, rest = match.group(1).strip(), match.group(2).strip()
    try:
        sku = sku_from_cell(reference, column)
    except ServiceRejectionError:
        return name, None
    if await SkuService.lookup_by_sku_async(db, org_id, sku):
        return rest, sku
    return name, None


def _keeps_its_own_sku(card: ProductTemplate, org_id: UUID, sku: str) -> bool:
    """Whether *card* already carries another code somebody gave it."""
    return bool(
        card.organization_id == org_id
        and card.sku
        and card.sku != sku
        and not card.sku.startswith(PLACEHOLDER_SKU_PREFIX)
    )


async def match_product(
    db: AsyncSession,
    org_id: UUID,
    *,
    name: str,
    barcode: str | None,
    brand: str | None,
    sku: str | None,
) -> tuple[ProductTemplate | None, str | None, bool]:
    """The product a row is about, the SKU to write on it, and whether it varies.

    A SKU names the product before anything else. Without one found, the
    barcode and then the name match as they do for the form. A product that
    carries another code keeps it: matched by the barcode it is the same
    product, matched by name alone it is not — variants share a name and
    differ by code — and the row *varies*: it is a product of its own.
    """
    if sku:
        by_sku = await SkuService.lookup_by_sku_async(db, org_id, sku)
        if by_sku is not None:
            return cast(ProductTemplate, by_sku), sku, False
    card = await find_template_async(
        db, org_id, name=name, barcode=barcode, brand=brand
    )
    if card is None or not sku or not _keeps_its_own_sku(card, org_id, sku):
        return card, sku, False
    if barcode and card.barcode == barcode:
        return card, None, False
    return None, sku, True


@dataclass
class RowProduct:
    """What a record of a row takes from the product it belongs to."""

    #: The product's own name where it exists: a record called "Imported
    #: Tuna" filed under Plum Butter would show the wrong one on every list.
    name: str
    sku: str | None
    #: Set only where the form's own matching would not land on the product —
    #: a record told its product outright keeps a barcode that product lacks.
    template_id: UUID | None
    #: The product existed before this record.
    exists: bool


async def product_of_a_record(
    db: AsyncSession,
    user: UserContextDTO,
    org_id: UUID,
    *,
    name: str,
    brand: str | None,
    barcode: str | None,
    sku: str | None,
    description: str | None,
    uom_id: UUID | None,
) -> RowProduct:
    """The product a record of the row joins, founding a variant first."""
    card, sku, varies = await match_product(
        db, org_id, name=name, barcode=barcode, brand=brand, sku=sku
    )
    if varies:
        variant = cast(
            ProductTemplate,
            await create_product_template_async(
                db,
                org_id,
                name,
                brand=brand,
                barcode=barcode,
                sku=sku,
                description=description,
                uom_id=uom_id,
                user_id=user.id,
            ),
        )
        return RowProduct(name, sku, variant.id, exists=False)
    if card is None:
        return RowProduct(name, sku, None, exists=False)
    found = await find_template_async(
        db, org_id, name=card.name, barcode=barcode, brand=brand
    )
    named = None if found is not None and found.id == card.id else card.id
    return RowProduct(card.name, sku, named, exists=True)


async def add_product_without_stock(
    db: AsyncSession,
    user: UserContextDTO,
    org_id: UUID,
    *,
    name: str,
    brand: str | None,
    barcode: str | None,
    sku: str | None,
    description: str | None,
    uom_id: UUID | None,
    min_quantity: float | None,
) -> bool:
    """Add the row's product to the catalogue; ``False`` when it is here already.

    A product that is here is left as it is.
    """
    card, sku, varies = await match_product(
        db, org_id, name=name, barcode=barcode, brand=brand, sku=sku
    )
    if card is not None:
        return False
    if not varies and barcode and await live_record_wearing_async(db, org_id, barcode):
        return False
    await create_product_template_async(
        db,
        org_id,
        name,
        brand=brand,
        barcode=barcode,
        sku=sku,
        description=description,
        uom_id=uom_id,
        min_quantity=min_quantity,
        user_id=user.id,
    )
    return True
