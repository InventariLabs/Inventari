"""The demo's label sheet: one A4 of the sandbox's own shelves and products.

Every visitor of the demo is handed an organization of their own, seeded
from the same rows in the same order, and the dressing numbers its shelves
the way a warehouse names its racks (``A-01``, ``A-01-01``) and gives its
products barcodes drawn from their own names — so the same sheet comes out
of every sandbox and every code printed on it resolves in whichever sandbox
the visitor was handed. That is what makes printing it worth a sheet of
paper: a visitor prints this once, before setting up a warehouse of their
own, and scans the printed codes with a phone — receive, put away, pick.

Only the labels come from Core (locations, product templates, through
``core_api``); the drawing is this module's own, at the size a phone camera
and a USB 1D scanner both read.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StorageDTO
from app.core.public_api import core_api
from app.modules.printing.services.print_queue_service import location_labels_async
from app.modules.printing.services.product_label_service import (
    ProductLabel,
    generate_product_label_batch_png,
    symbology,
)

#: The sheet's geometry: four 50 x 24 mm labels across, which is one A4
#: (210 x 297 mm) of 48 labels with room to spare — the demo's shelves plus
#: a handful of products fit on the one page, drawn at real size at
#: ``LABEL_DPI`` so the printed bars keep the width a scanner reads.
LABEL_WIDTH_MM = 50.0
LABEL_HEIGHT_MM = 24.0
LABEL_COLUMNS = 4

#: How much of the sandbox the one sheet carries: the shelves down to the
#: page, and a handful of products under them.
MAX_SHELF_LABELS = 40
PRODUCT_LABELS = 8


async def demo_label_sheet_async(
    db: AsyncSession, organization_id: UUID
) -> tuple[list[ProductLabel], bytes]:
    """The sandbox's label sheet: the labels it prints, and the PNG of them.

    Two sandboxes seeded from the same rows answer with the same labels and
    the same bytes — no dates on the labels, no ids in the order they are
    laid out in — which is how a printed sheet can be read as *the* demo's
    sheet wherever it was printed.
    """
    shelves = await _shelf_labels(db, organization_id)
    products = await _product_labels(db, organization_id)
    labels = [*shelves, *products]
    png = generate_product_label_batch_png(
        labels, LABEL_WIDTH_MM, LABEL_HEIGHT_MM, columns=LABEL_COLUMNS
    )
    return labels, png


async def _shelf_labels(db: AsyncSession, organization_id: UUID) -> list[ProductLabel]:
    """The sandbox's shelves: every leaf place under a warehouse, in walk
    order, at most ``MAX_SHELF_LABELS`` of them.

    The walk goes by names — ancestors' names from the warehouse down, never
    ids — because two sandboxes hold the same names in the same tree and no
    two of them share an id. A place whose parent is not one of these rows
    (a non-internal parent, an archived one) was not numbered with the tree,
    so it does not belong on a sheet meant to scan.
    """
    storages = await core_api.locations.list_async(
        db, organization_id, usage='internal', limit=500
    )
    by_id = {storage.id: storage for storage in storages}
    children: dict[UUID, int] = {}
    for storage in storages:
        if storage.parent_id is not None:
            children[storage.parent_id] = children.get(storage.parent_id, 0) + 1

    def walk(storage: StorageDTO) -> str:
        names: list[str] = []
        current: StorageDTO | None = storage
        while current is not None:
            names.append(current.name.casefold())
            current = by_id.get(current.parent_id) if current.parent_id else None
        return '/'.join(reversed(names))

    leaves = [
        storage
        for storage in storages
        if storage.parent_id is not None
        and storage.parent_id in by_id
        and storage.id not in children
    ]
    chosen = sorted(leaves, key=walk)[:MAX_SHELF_LABELS]
    labels, _without_code = await location_labels_async(
        db, organization_id, [storage.id for storage in chosen], qr=False
    )
    return labels


async def _product_labels(
    db: AsyncSession, organization_id: UUID
) -> list[ProductLabel]:
    """A handful of the sandbox's own products: the first by name with a
    code that draws, at most ``PRODUCT_LABELS`` of them.

    Name order and the org's own templates only — global ones aside, no ids
    in the choice — so every sandbox prints the same handful, down to the
    barcodes the seed drew from each product's name.
    """
    templates = [
        template
        for template in await core_api.product_templates.list_for_org_async(
            db, organization_id, limit=500
        )
        if template.organization_id == organization_id
    ]
    ordered = sorted(
        templates, key=lambda t: (t.name.casefold(), t.name, t.barcode or '')
    )
    labels: list[ProductLabel] = []
    for template in ordered:
        if not template.barcode or symbology(template.barcode) is None:
            continue
        labels.append(ProductLabel(name=template.name, code=template.barcode))
        if len(labels) == PRODUCT_LABELS:
            break
    return labels
