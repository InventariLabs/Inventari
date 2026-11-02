from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.contracts import UserContextDTO
from app.core.label_codes import LABEL_CODE_PATTERN
from app.core.open_package import opened_at
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.item import Item as ItemSchema
from app.schemas.label_pool import LabelScanResponse
from app.services._product_template_reads import template_by_code_query
from app.services._stock_quant_query import list_quants_async
from app.services.stock_strategy import resolve_removal_strategy
from app.services.storage_query_service import location_paths_async

_DIGITS_BARCODE = re.compile(r'^\d{8,14}$')

# Recognises a label short_code (e.g. STM-2BWO, B12-6UPR, DELL-LAT5540).
# The shape is defined once, beside the constraint the creation schema
# reads, because the two used to disagree about digits and the
# disagreement printed stickers the scanner refused: see
# `app.core.label_codes`. Re-exported here so the provider chain and the
# legacy scan service keep their existing import.


async def _scalars_first(db: AsyncSession, query: Select[Any]) -> Any:
    result = await db.scalars(query)
    return result.first()


async def _scalars_all(db: AsyncSession, query: Select[Any]) -> list[Any]:
    result = await db.scalars(query)
    return list(result.all())


def _storage_context(storage: StorageLocation, label_code: str) -> LabelScanResponse:
    """The answer to a scan that names a shelf: the shelf becomes the context."""
    return LabelScanResponse(
        status='storage_context',
        label_code=label_code,
        message_key='scan:storageContextSet',
        message_params={'name': storage.name},
        action='set_storage_context',
        location={
            'id': str(storage.id),
            'name': storage.name,
            'icon': storage.storage_type.icon if storage.storage_type else '📦',
            'type_code': storage.storage_type.type_code
            if storage.storage_type
            else 'GENERIC',
        },
    )


class StorageScanProvider:
    async def can_handle(self, code: str) -> bool:
        return True

    async def handle(
        self, code: str, user: UserContextDTO, db: AsyncSession
    ) -> LabelScanResponse | None:
        storage = await _scalars_first(
            db,
            select(StorageLocation).where(
                StorageLocation.short_code == code,
                StorageLocation.organization_id == user.organization_id,
            ),
        )

        if storage is None:
            return await self._renumbered_async(code, user, db)
        return _storage_context(storage, storage.short_code or '')

    @staticmethod
    async def _renumbered_async(
        code: str, user: UserContextDTO, db: AsyncSession
    ) -> LabelScanResponse | None:
        """The location an old code of a renumbered location names.

        The old code stays behind as a storage pool label aimed at the
        location, and it need not have a label's shape (``SHELF1``,
        ``A-02-01``) — the pool provider only looks at codes that do. The
        scan is counted on the label like any pool label's.
        """
        found = (
            await db.execute(
                select(LabelPool.id, StorageLocation)
                .join(
                    StorageLocation,
                    StorageLocation.id == LabelPool.target_storage_location_id,
                )
                .options(joinedload(StorageLocation.storage_type))
                .where(
                    LabelPool.short_code == code,
                    LabelPool.organization_id == user.organization_id,
                    LabelPool.label_type == 'STORAGE',
                    StorageLocation.organization_id == user.organization_id,
                )
            )
        ).first()
        if found is None:
            return None
        label_id, storage = found
        from sqlalchemy import update

        await db.execute(
            update(LabelPool)
            .where(LabelPool.id == label_id)
            .values(
                scan_count=LabelPool.scan_count + 1,
                last_scanned_at=datetime.now(UTC),
            )
        )
        return _storage_context(storage, code)


class LabelPoolScanProvider:
    async def can_handle(self, code: str) -> bool:
        return bool(LABEL_CODE_PATTERN.match(code))

    async def handle(
        self, code: str, user: UserContextDTO, db: AsyncSession
    ) -> LabelScanResponse | None:
        # Scope the lookup by organization so a foreign-org label falls
        # through (returns None) to the next provider instead of raising 403,
        # which leaked label existence across tenants. Returning None lets the
        # scan chain keep trying (e.g. a barcode provider) without confirming
        # to the caller that the code exists in another org.
        label = await _scalars_first(
            db,
            select(LabelPool).where(
                LabelPool.short_code == code,
                LabelPool.organization_id == user.organization_id,
            ),
        )
        if not label:
            return None

        # Atomic increment to prevent lost updates under concurrent scans.
        # The ORM-enabled UPDATE mirrors the incremented value onto the
        # loaded object, so assigning it again here would count this scan
        # twice: once in the row, once in the object flushed at commit.
        from sqlalchemy import update

        await db.execute(
            update(LabelPool)
            .where(LabelPool.id == label.id)
            .values(
                scan_count=LabelPool.scan_count + 1,
                last_scanned_at=datetime.now(UTC),
            )
        )
        # The count rides the caller's transaction: one scan, one commit,
        # made by the request-scoped session — a count that survives a
        # later failure of its own handling is a fact nobody asked for.

        if label.label_type == 'STORAGE' and label.target_storage_location_id:
            storage = label.target_storage
            return _storage_context(storage, label.short_code)

        if not label.is_assigned or not label.item_id:
            return LabelScanResponse(
                status='unassigned',
                label_code=label.short_code,
                message_key='scan:result.labelReady',
                action='show_quick_add',
                context_tag=label.context_tag,
            )

        item = await _scalars_first(
            db,
            select(Item)
            .options(joinedload(Item.category), joinedload(Item.uom))
            .where(Item.id == label.item_id),
        )

        if not item:
            label.is_assigned = False
            label.item_id = None
            await db.flush()
            return LabelScanResponse(
                status='unassigned',
                label_code=label.short_code,
                message_key='scan:result.labelReady',
                action='show_quick_add',
                context_tag=label.context_tag,
            )

        if item.is_deleted:
            return LabelScanResponse(
                status='archived',
                label_code=label.short_code,
                message_key='scan:result.previously',
                message_params={'product': item.name},
                action='show_archived_info',
                item=ItemSchema.model_validate(item).model_dump(),
                context_tag=item.category.context_tag
                if item.category
                else label.context_tag,
            )

        return LabelScanResponse(
            status='assigned',
            label_code=label.short_code,
            message_key='scan:result.product',
            message_params={'product': item.name},
            action='show_quick_actions',
            item=ItemSchema.model_validate(item).model_dump(),
            quick_actions=['consume', 'discard', 'move', 'view_details'],
            context_tag=item.category.context_tag
            if item.category
            else label.context_tag,
        )


def _template_payload(
    template: ProductTemplate | None,
    best_item: Item | None,
    storage_location_id: str | None,
) -> dict[str, Any]:
    """What the quick-add form needs to open on the product that was scanned.

    Read from the catalogue row when the code named one — a template holds the
    name, the brand, the unit and the unit weight whether or not the
    organization has any of it on a shelf right now. The record adds what only
    a record knows: which category it was filed under, where it stands and
    whatever a vision capture left behind.
    """
    source_template = template or (best_item.template if best_item else None)
    return {
        # Lets a caller holding catalogue-only lines (a document line with a
        # product but no stock record) tell whether the scan is that product.
        'id': str(source_template.id) if source_template else None,
        'name': template.name if template else (best_item.name if best_item else None),
        'brand': template.brand
        if template
        else (best_item.brand if best_item else None),
        'sku': source_template.sku if source_template else None,
        'unit': best_item.uom.symbol
        if best_item and best_item.uom
        else (
            source_template.uom.symbol
            if source_template and source_template.uom
            else None
        ),
        'uom_id': str(best_item.uom_id)
        if best_item and best_item.uom_id
        else (
            str(source_template.uom_id)
            if source_template and source_template.uom_id
            else None
        ),
        'category_id': str(best_item.category_id)
        if best_item and best_item.category_id
        else None,
        'location_id': storage_location_id,
        # Unit weight, straight from the product template — that is where
        # the quick-add form puts it back (ADR-015).
        'weight_value': source_template.weight_value if source_template else None,
        'weight_uom_id': str(source_template.weight_uom_id)
        if source_template and source_template.weight_uom_id
        else None,
        # What one piece holds, for a card that measures in volume; the scan
        # sheet restates a partly used package in it.
        'volume_value': float(source_template.volume_value)
        if source_template and source_template.volume_value is not None
        else None,
        'volume_uom_id': str(source_template.volume_uom_id)
        if source_template and source_template.volume_uom_id
        else None,
        'metadata': best_item.meta_data if best_item else None,
    }


class BarcodeScanProvider:
    async def can_handle(self, code: str) -> bool:
        # Any code: a SKU or an alphanumeric barcode is as good a name for a
        # product as an EAN. This is the last provider in the chain, so
        # locations, labels, documents and Open Food Facts have all had their
        # turn; what is left is answered from the catalogue or not at all.
        return bool(code)

    @staticmethod
    async def _template_for(
        code: str, user: UserContextDTO, db: AsyncSession
    ) -> ProductTemplate | None:
        """The catalogue row this code names, the organization's own first.

        A template may be global — the shipped catalogue is one row shared by
        every organization — and stock points at it by ``template_id`` all the
        same. An organization that has its own row for the code means it, so
        that one is preferred; the query orders it first. The code is a
        barcode or a SKU: see :func:`template_by_code_query`.
        """
        if user.organization_id is None:
            return None
        # Annotated rather than returned straight: the shared helper answers
        # Any, and mypy refuses to launder that through a typed signature.
        row: ProductTemplate | None = await _scalars_first(
            db,
            # The payload reads the unit off this row; a relationship touched
            # outside a load raises rather than answering here.
            template_by_code_query(user.organization_id, code).options(
                joinedload(ProductTemplate.uom)
            ),
        )
        return row

    @staticmethod
    async def _places(
        db: AsyncSession,
        user: UserContextDTO,
        items: list[Item],
        strategy: str,
    ) -> dict[str, Any]:
        """What the sheet says about each record beyond the record itself."""
        org_id = user.organization_id
        if org_id is None:
            return {'paths': {}, 'lots': {}, 'reserved': {}}
        locations = {i.storage_location_id: i.storage_location for i in items}
        lot_ids = {i.lot_id for i in items if i.lot_id}
        lot_names: dict[UUID, str] = {}
        if lot_ids:
            rows = await db.execute(
                select(StockLot.id, StockLot.name).where(
                    StockLot.id.in_(lot_ids), StockLot.organization_id == org_id
                )
            )
            lot_names = dict(rows.tuples().all())
        template_ids = {i.template_id for i in items if i.template_id}
        quants = (
            await list_quants_async(db, org_id, product_template_ids=list(template_ids))
            if template_ids
            else []
        )
        return {
            'paths': await location_paths_async(db, org_id, list(locations.values())),
            'lots': lot_names,
            'reserved': BarcodeScanProvider._reserved_per_record(
                items,
                {
                    (q.storage_location_id, q.lot_id, q.owner_id): float(
                        q.reserved_quantity
                    )
                    for q in quants
                },
                strategy,
            ),
        }

    @staticmethod
    def _reserved_per_record(
        items: list[Item], held: dict[tuple[Any, ...], float], strategy: str
    ) -> dict[UUID, float]:
        """Split each group's hold across its records, the way a draw leaves it.

        The reservation rows name a (shelf, batch, owner) group, not a
        record, and a group holds several records whenever a receipt did not
        top one up. A draw takes the group's free part from the first record
        in removal order on, so the hold sits on the last ones: the parts
        sum to the hold and none goes beyond its record's quantity.
        """
        if strategy == 'FEFO':
            # Undated stock leaves after dated stock, like the draw's order.
            def order(i: Item) -> tuple[Any, ...]:
                day = i.effective_expiry_date
                return (day is None, day, i.created_at, i.id)
        else:

            def order(i: Item) -> tuple[Any, ...]:
                return (i.created_at, i.id)

        left = dict(held)
        reserved: dict[UUID, float] = {}
        for item in sorted(items, key=order, reverse=True):
            grain = (item.storage_location_id, item.lot_id, item.owner_id)
            part = min(float(item.quantity), left.get(grain, 0.0))
            left[grain] = left.get(grain, 0.0) - part
            reserved[item.id] = part
        return reserved

    @staticmethod
    def _stock_row(item: Item, places: dict[str, Any]) -> dict[str, Any]:
        reserved = places['reserved'].get(item.id, 0.0)
        return {
            'id': str(item.id),
            'location_id': str(item.storage_location_id),
            # FIFO's order: the record that landed first leaves first.
            'created_at': item.created_at.isoformat(),
            'opened_at': opened_at(item.meta_data),
            # The day the record is judged by: the batch's date or, if
            # earlier, the use-by given when it was opened. The sheet
            # shows it and takes the earliest first.
            'expiry_date': item.effective_expiry_date.isoformat()
            if item.effective_expiry_date
            else None,
            'location': item.storage_location.name,
            # Two shelves can share a name; the path and the shelf's code
            # tell them apart where the picker stands.
            'location_path': places['paths'].get(
                item.storage_location_id, item.storage_location.name
            ),
            'location_code': item.storage_location.short_code,
            'lot': places['lots'].get(item.lot_id),
            'quantity': float(item.quantity),
            'reserved_quantity': reserved,
            'available_quantity': float(item.quantity) - reserved,
        }

    async def handle(
        self, code: str, user: UserContextDTO, db: AsyncSession
    ) -> LabelScanResponse | None:
        """Answer "what do I have of this?" for a code read off a package.

        The barcode belongs to the product template: that is where a receipt
        writes it, and ``uq_items_org_barcode_active`` lets only one active
        record bear one — so asking the item column meant asking a column that
        is empty in practice and could never hold the answer this branch is
        written for anyway (it sums rows and lists places).

        So identity comes from the template, and the item column answers only
        for records that have no template. That is the precedence
        ``find_stock_row_async`` already applies to a delivery naming a
        product, and the two now agree.
        """
        template = await self._template_for(code, user, db)

        if template is not None:
            all_items = await _scalars_all(
                db,
                select(Item)
                .join(StorageLocation)
                .where(
                    Item.template_id == template.id,
                    Item.organization_id == user.organization_id,
                    # An asset in an equipment register is not warehouse
                    # stock, even when it shares a template with some.
                    Item.module_name.is_(None),
                )
                .options(joinedload(Item.storage_location), joinedload(Item.template))
                .order_by(Item.created_at.desc()),
            )
        else:
            all_items = await _scalars_all(
                db,
                select(Item)
                .join(StorageLocation)
                .where(
                    Item.barcode == code,
                    StorageLocation.organization_id == user.organization_id,
                )
                .options(joinedload(Item.storage_location), joinedload(Item.template))
                .order_by(Item.created_at.desc()),
            )

        active_items = [item for item in all_items if not item.is_deleted]

        if not all_items:
            if template is None:
                # Digits are a package barcode nobody has registered yet: add
                # the product. Any other text is no evidence of a product at
                # all, so it stays unrecognized and the screen offers a search.
                if not _DIGITS_BARCODE.match(code):
                    return None
                return LabelScanResponse(
                    status='unassigned',
                    label_code=code,
                    message_key='scan:result.newProduct',
                    action='show_quick_add',
                )
            # Still "add one", but not from a blank form: the catalogue knows
            # what was scanned. The empty New Product form was the visible
            # half of this bug.
            return LabelScanResponse(
                status='unassigned',
                label_code=code,
                message_key='scan:result.notInStock',
                message_params={'product': template.name},
                action='show_quick_add',
                stock_summary={
                    'template': _template_payload(template, None, None),
                    'total_quantity': 0,
                    'items': [],
                },
            )

        def get_item_score(item: Item) -> int:
            score = 0
            if item.meta_data:
                score += 1
                if item.meta_data.get('nutrition_source') == 'vision_capture':
                    score += 10
            return score

        best_item = sorted(
            all_items, key=lambda x: (get_item_score(x), x.created_at), reverse=True
        )[0]

        real_storage_location_id = None
        for candidate in sorted(
            all_items, key=lambda x: (get_item_score(x), x.created_at), reverse=True
        ):
            if (
                candidate.storage_location
                and candidate.storage_location.usage == LocationUsage.INTERNAL
                and candidate.storage_location_id
            ):
                real_storage_location_id = str(candidate.storage_location_id)
                break

        template_payload = _template_payload(
            template, best_item, real_storage_location_id
        )

        if not active_items:
            return LabelScanResponse(
                status='unassigned',
                label_code=code,
                message_key='scan:result.foundInHistory',
                message_params={'product': best_item.name},
                action='show_quick_add',
                stock_summary={
                    'template': template_payload,
                    'total_quantity': 0,
                    'items': [],
                },
            )

        total_quantity = sum(item.quantity for item in active_items)
        strategy = resolve_removal_strategy(template or best_item.template)
        places = await self._places(db, user, active_items, strategy)
        locations = list({item.storage_location.name for item in active_items})

        stock_summary = {
            'total_quantity': float(total_quantity),
            'unit': best_item.uom.symbol if best_item.uom else None,
            'locations': locations,
            'template': template_payload,
            # How the product leaves a shelf. The sheet lists records as they
            # come; a document taking goods off a shelf has to pick one, and
            # picks it by this.
            'removal_strategy': strategy,
            'items': [self._stock_row(item, places) for item in active_items],
        }

        return LabelScanResponse(
            status='product_stock',
            label_code=code,
            message_key='scan:result.product',
            message_params={'product': template.name if template else best_item.name},
            action='show_stock_actions',
            stock_summary=stock_summary,
        )
