"""What a typed string is matched against when someone searches for a record.

One predicate, four call sites (the items list, its cursor-paginated twin,
the filtered query behind the screen, and the trash), because the four used
to hold four copies of the same ``or_`` and a code added to one of them was
missing from the others.

The product code is the reason this file exists. A scanned barcode belongs
to the *product*, so it is written to the template and the record stays
bare — while the searches asked ``Item.barcode`` alone and answered "no
results" for a product the organization had just scanned in. A code can sit
on either carrier (the record keeps its own when there is no catalogue
entry behind it), so the search asks both.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, any_, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import aliased

from app.core.db_utils import SUBSTRING_MIN_LENGTH, typed_fragment_pattern
from app.models.item import Item
from app.models.product_template import ProductTemplate


def _own_fields_match(record: type[Item], pattern: str) -> ColumnElement[bool]:
    return or_(
        record.name.ilike(pattern),
        record.brand.ilike(pattern),
        record.barcode.ilike(pattern),
        record.label_code.ilike(pattern),
        # Assets are identified by the number on the sticker, and the
        # reader holding one types it here first.
        record.serial_number.ilike(pattern),
    )


def item_matches_text(
    text: str, organization_id: UUID | None = None
) -> ColumnElement[bool]:
    """The record's own fields, plus the product code of its template.

    Asked as a set of record ids, one branch per carrier, and not as one
    ``OR`` over the row: each branch is answered by its own trigram indexes,
    while a single ``OR`` that also reaches into the template can be
    answered by none of them, so every search read every record of every
    organization (two seconds for one barcode at a hundred thousand
    products). *organization_id*, when the caller has it, scopes both
    branches: the product code's finds the records of the matched products
    by the organization's own index instead of reading every record, and the
    own-fields branch no longer reads the matches of every other
    organization before the outer scope drops them.

    One or two letters match the start of each field, as in the product
    picker: a fragment that short has no trigram to look up anywhere else,
    so "he" anywhere read every record of the organization. They are asked
    of the row, not as a set (``_matches_a_short_fragment``).
    """
    pattern = typed_fragment_pattern(text)
    if len(text) < SUBSTRING_MIN_LENGTH:
        return _matches_a_short_fragment(text, pattern, organization_id)
    record = aliased(Item)
    own_fields = select(record.id).where(_own_fields_match(record, pattern))
    # The code a scan wrote: it lives on the product, not on the row.
    by_product_code = select(record.id).where(
        record.template_id.in_(
            select(ProductTemplate.id).where(ProductTemplate.barcode.ilike(pattern))
        )
    )
    if organization_id is not None:
        own_fields = own_fields.where(record.organization_id == organization_id)
        by_product_code = by_product_code.where(
            record.organization_id == organization_id
        )
    return Item.id.in_(own_fields.union(by_product_code))


def _matches_a_short_fragment(
    text: str, pattern: str, organization_id: UUID | None
) -> ColumnElement[bool]:
    """One or two characters, asked of the row itself rather than as a set.

    A letter begins a tenth of a catalogue, and the set of record ids had to
    be gathered whole — every match read, then sorted — before the page
    could keep fifty: "h" took 280 ms of the database at a hundred thousand
    products. Asked of the row, the planner walks the page's own order and
    stops at fifty when the fragment is common, and looks the fields' indexes
    up when it is rare.

    That holds only while the product's branch is a value the indexes can
    take, so its ids come as one array, and it holds only while the array is
    small: the product code is matched whole here, as the picker matches it.
    Its first one or two digits are the country's (every Polish EAN begins
    590), so "the code begins with 5" named most of a catalogue and put
    every product id into the statement.
    """
    product_codes = select(ProductTemplate.id).where(ProductTemplate.barcode == text)
    if organization_id is not None:
        product_codes = product_codes.where(
            ProductTemplate.organization_id == organization_id
        )
    return or_(
        _own_fields_match(Item, pattern),
        Item.template_id
        == any_(
            func.array(
                product_codes.scalar_subquery(), type_=ARRAY(ProductTemplate.id.type)
            )
        ),
    )
