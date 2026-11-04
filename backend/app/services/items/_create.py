from __future__ import annotations

from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.db_utils import get_org_owned_or_404_async
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import (
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.interceptors import interceptor_pipeline
from app.core.money import quantise
from app.i18n.service import get_current_lang
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.schemas._common import keyed_by_column
from app.schemas.item import ItemCreate, _take_unit_confirmation
from app.services.audit_service import log_action_async

from ._loaded import read_back_a_new_record, settle_category
from ._module_owner import resolve_module_owner
from ._product_code import place_product_code_async
from ._quota import check_item_quota_async
from ._stock_quant import apply_quantity_change_async
from ._template import resolve_template_for_create_async
from ._unit_choice import (
    keep_in_card_unit_async,
    log_unit_chosen_over_template_async,
    refuse_unconfirmed_unit_difference_async,
)
from .history import log_history_async


async def _ensure_storage_async(
    db: AsyncSession,
    item_in: ItemCreate,
    org_id: UUID,
) -> StorageLocation:
    storage = await _fetch_own_storage_or_404_async(db, item_in.location_id, org_id)
    # An archived location is off every picker, so a product stored there
    # shows its location as "Unknown" and cannot be moved back. The screen
    # used to offer "Add product" and the server answered 201.
    if (storage.settings or {}).get('archived') is True:
        raise catalogue_refusal('storage_archived')
    return storage


async def _fetch_own_storage_or_404_async(
    db: AsyncSession,
    storage_location_id: UUID,
    org_id: UUID,
) -> StorageLocation:
    """The one place a ``storage_location_id`` is checked against its owner."""
    return await get_org_owned_or_404_async(
        db,
        StorageLocation,
        storage_location_id,
        org_id,
        resource='storage',
        lang=get_current_lang(),
    )


async def _ensure_storage_location_async(
    db: AsyncSession,
    storage_location_id: UUID | None,
    org_id: UUID,
) -> None:
    """Refuse a ``storage_location_id`` owned by another organization.

    The column decides who can see the record at all: both the item list and
    the detail fetch are scoped by the locations the caller owns. Create ran
    this check through :func:`_ensure_storage_async`; update and bulk update
    let the id fall through to a plain ``setattr``, so a record could be
    parked on another organization's shelf — where it became theirs to read
    and to write, and where its stock followed it.

    404 rather than 403, for the same reason as the category guard: a 403
    would confirm the row exists.
    """
    if storage_location_id is None:
        return

    await _fetch_own_storage_or_404_async(db, storage_location_id, org_id)


async def _ensure_category_async(
    db: AsyncSession,
    category_id: UUID | None,
    org_id: UUID,
) -> Category | None:
    """Refuse a ``category_id`` owned by another organization.

    The item response serialises the whole category (name, field_definitions),
    so an unchecked id let organization A read B's category configuration —
    the storage location on the same request was guarded, the category was not.

    ``Category.organization_id`` is nullable by design (global categories),
    so ``get_org_owned_or_404_async`` is too strict here: the rule is "mine or
    global". 404 rather than 403 — a 403 would confirm the row exists.

    Returns the row it validated, the way :func:`_ensure_storage_async` does,
    so a caller that records the id can record its name without reading the
    row a second time.

    Deliberately NOT folded into
    :func:`_validate_metadata_against_category_async`: that one returns early
    for items without a category, which would skip the check for most items.
    """
    if category_id is None:
        return None

    category = await db.get(Category, category_id)
    if category is None or category.organization_id not in (None, org_id):
        raise NotFoundException('category', get_current_lang())
    return category


async def _ensure_uom_async(
    db: AsyncSession,
    uom_id: UUID,
    org_id: UUID,
) -> None:
    """Refuse a ``uom_id`` owned by another organization.

    The item response embeds the unit (symbol, name, conversion factor), so
    an unchecked id let organization A read B's unit definition and run its
    quantity conversions on B's factor — the category on the same request
    was guarded, the unit was not.

    ``Uom.organization_id`` is nullable by design (system units), so the
    rule is "mine or global", as for categories. 404 rather than 403 — a
    403 would confirm the row exists.
    """
    uom = await db.get(Uom, uom_id)
    if uom is None or uom.organization_id not in (None, org_id):
        raise NotFoundException('uom', get_current_lang())


async def _validate_metadata_against_category_async(
    db: AsyncSession,
    item_data: dict[str, Any],
) -> None:
    """Validate ``item_data['meta_data']`` against the category's
    ``field_definitions`` (the money/multi-select/select value
    contract). No-op when the item has no category or no custom metadata.

    A custom field the category marks required must be filled: the add form
    has always insisted, and the import and the API are the doors with no form
    to do it for them.

    Raises :class:`FieldValueError` (a ``ValueError`` subclass) on a contract
    violation; the API router maps that to HTTP 400.
    """
    from app.models.category import Category
    from app.services.fields.validation import (
        refuse_missing_required_fields,
        validate_item_metadata_fields,
    )

    category_id = item_data.get('category_id')
    if not category_id:
        return

    category = await db.get(Category, category_id)
    if category is None:
        return
    refuse_missing_required_fields(
        item_data.get('meta_data'), category.field_definitions
    )
    validate_item_metadata_fields(
        item_data.get('meta_data'), category.field_definitions
    )


async def _ensure_serial_unique_async(
    db: AsyncSession,
    org_id: UUID,
    serial: str,
    exclude_item_id: UUID | None = None,
) -> None:
    """Raise ValueError when another item in the org holds *serial*.

    Shared by create and update; the update path previously stripped
    twice and reported the unstripped value in the error message.
    """
    sn = serial.strip()
    if not sn:
        return
    stmt = select(Item).where(
        Item.organization_id == org_id,
        Item.serial_number == sn,
        Item.is_deleted.is_(False),
    )
    if exclude_item_id is not None:
        stmt = stmt.where(Item.id != exclude_item_id)
    duplicate = await db.scalar(stmt)
    if duplicate:
        raise ServiceRejectionError('serial_number_exists', serial_number=sn)


async def _ensure_barcode_unique_async(
    db: AsyncSession,
    org_id: UUID,
    barcode: str,
    exclude_item_id: UUID | None = None,
) -> None:
    """Raise ValueError when another live item in the org holds *barcode*.

    One rule for create and update, so both paths say the same sentence.
    Without it, creation answered a taken barcode with the
    ``uq_items_org_barcode_active`` index — a raw 500 — where the very same
    collision on the edit path was a clean refusal.

    Check-then-insert, so not atomic: two concurrent creates on one barcode
    can both pass this SELECT and one then meets IntegrityError — a raw 500
    again, since the IntegrityError handler deliberately leaves unique keys
    alone. The same narrow window the serial-number check has.
    """
    stmt = select(Item).where(
        Item.organization_id == org_id,
        Item.barcode == barcode,
        Item.is_deleted.is_(False),
    )
    if exclude_item_id is not None:
        stmt = stmt.where(Item.id != exclude_item_id)
    duplicate = await db.scalar(stmt)
    if duplicate:
        refuse_taken_barcode(barcode)


def refuse_taken_barcode(barcode: str) -> NoReturn:
    """The one sentence a taken code is refused with, whichever carrier has it."""
    raise ServiceRejectionError('barcode_in_use', barcode=barcode)


async def _validate_quantity_precision_async(
    db: AsyncSession,
    item_data: dict[str, Any],
) -> None:
    """Refuse a quantity the record's unit cannot hold.

    The unit must already be settled on ``item_data`` — callers resolve it
    first, so the gate measures the unit the row will land with rather than
    the one the request happened to name. A quantity with no unit at all is
    the one thing this cannot judge, and it is a shape the resolver already
    refuses.
    """
    uom_id = item_data.get('uom_id')
    quantity = item_data.get('quantity')
    if not (uom_id and quantity is not None):
        return
    from app.services.uom_service import validate_quantity_precision_async

    await validate_quantity_precision_async(db, uom_id, Decimal(str(quantity)))


async def _default_piece_uom_id_async(
    db: AsyncSession,
    org_id: UUID,
) -> UUID:
    """The unit a product gets when nobody chose one: pieces.

    Odoo defaults Units, ERPNext mandates a Default UoM, Zoho preselects —
    "a quantity of what" is answered for the user, not asked. The
    organization's own 'pcs' row wins over the system one, so a tenant that
    renamed its piece keeps its vocabulary.

    An installation with no piece row anywhere cannot answer that question,
    and this is the one place that decides what happens then: the four doors
    that ask it — the record resolver below, the record update that mints a
    template for a record without one, the catalogue's own create, and the
    document quick-create stub — all inherit this answer. Answering ``None``
    let the blank travel on: each door minted a row whose unit column reads
    "—" and before which the BoM convertibility guard falls silent, with
    nothing in the response to tell the caller that "a quantity of what"
    went unanswered. So the third answer is the honest one, and each door
    already offers a way out: the two templates take a ``uom_id``, and the
    two record doors a record carrying one.
    """
    from app.services.uom_service import get_uom_by_symbol_async

    uom = await get_uom_by_symbol_async(db, 'pcs', org_id)
    if uom is None:
        raise ServiceRejectionError('piece_unit_missing_from_catalogue')
    return uom.id


async def _resolve_record_unit_async(
    db: AsyncSession,
    org_id: UUID,
    item_data: dict[str, Any],
    template: ProductTemplate,
) -> None:
    """Fill a unit the caller left unset: the matched template's, else pieces.

    A matched template is knowledge, and the default yields to it: a record
    contradicting its own catalogue row about the unit meant the BoM
    convertibility guard — which reads the template — checked a different
    number than the shelf held. Pieces stay the answer for a
    product the catalogue says nothing about."""
    if item_data.get('uom_id'):
        await _ensure_uom_async(db, item_data['uom_id'], org_id)
        return
    if template.uom_id is not None:
        item_data['uom_id'] = template.uom_id
    else:
        item_data['uom_id'] = await _default_piece_uom_id_async(db, org_id)


async def _settle_unit_choice_async(
    db: AsyncSession,
    item_data: dict[str, Any],
    template: ProductTemplate,
    matched_template_uom_id: UUID | None,
    *,
    confirmed: bool,
) -> tuple[UUID | None, Decimal | None]:
    """Refuse an unconfirmed unit difference; keep a confirmed one in the card's unit.

    A confirmed difference is restated in the matched card's unit, not kept
    in the chosen one: the movement, the cost layer and the records' view
    carry the number without a unit. Returns the unit and the quantity as they
    were entered, for the history row that says what was typed.
    """
    chosen_uom_id = item_data.get('uom_id')
    entered_quantity = item_data.get('quantity')
    await refuse_unconfirmed_unit_difference_async(
        db,
        template_uom_id=matched_template_uom_id,
        chosen_uom_id=chosen_uom_id,
        product_name=item_data.get('name'),
        confirmed=confirmed,
    )
    if matched_template_uom_id is not None:
        await keep_in_card_unit_async(
            db, item_data, template, product_name=item_data.get('name')
        )
    return chosen_uom_id, entered_quantity


async def _create_stock_entry_async(
    db: AsyncSession,
    item: Item,
    user_id: UUID | None = None,
) -> None:
    await apply_quantity_change_async(
        db,
        item,
        item.quantity,
        old_quantity=Decimal('0'),
        unit_cost=item.purchase_price,
        user_id=user_id,
    )


async def _log_item_created_async(
    db: AsyncSession,
    item: Item,
    user: UserContextDTO,
    source_document_id: UUID | None,
    history_changes: dict[str, Any] | None,
    action: ItemAction = ItemAction.CREATED,
) -> None:
    payload = {'created': True, **(history_changes or {})}
    await log_history_async(
        db,
        item,
        action,
        payload,
        user_id=user.id,
        source_document_id=source_document_id,
    )


async def _resolve_org_currency_async(
    db: AsyncSession,
    org_id: UUID,
) -> str | None:
    return await db.scalar(
        select(Organization.currency).where(Organization.id == org_id)
    )


async def _lock_record_group_async(db: AsyncSession, org_id: UUID, item: Item) -> None:
    """Hold the group a new record joins, creating its anchor, before it is written.

    The record's foreign key names its group's anchor, and the lock is what
    creates an anchor for a product the shelf has never held. A record
    without a card joins no group.
    """
    if item.template_id is None:
        return
    from app.services._stock_quant_ops import lock_stock_async

    await lock_stock_async(
        db, org_id, keys=[(item.template_id, item.storage_location_id)]
    )


async def create_item_async(
    db: AsyncSession,
    item_in: ItemCreate,
    user: UserContextDTO,
    source_document_id: UUID | None = None,
    history_changes: dict[str, Any] | None = None,
    post_the_change: bool = True,
    unit_confirmed_over_template: bool = False,
    history_action: ItemAction = ItemAction.CREATED,
    label_code: str | None = None,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
) -> Item:
    """Create one record, with its unit settled and accounted for.

    ``unit_confirmed_over_template`` is the same confirmation the request
    body carries (``ItemCreate``), for the callers that hold a schema rather
    than a request: an importer whose sheet column named a unit is making
    that choice itself, so it says so here. A caller that says nothing gets
    the honest refusal when the unit differs from the matched template's.

    ``history_action`` and ``label_code`` are the door's own identity, and
    they travel here rather than as a second create sequence: a scan is one
    more door into the same warehouse, and the row it writes is one more
    record of the same kind. ``history_action`` names that birth in the
    record's history (``CREATED_VIA_SCAN``), and ``label_code`` is the label
    the record is born wearing — stamped before the journal entry and the
    ``ITEM_CREATED`` event read it, because both serialise the row at the
    moment they are written.

    ``lot_id`` and ``owner_id`` name the batch and owner the record's stock
    is in, for a caller that knows them.
    """
    if user.organization_id is None:
        raise ServiceRejectionError('user_has_no_organization')
    org_id = user.organization_id

    # Same gate as the scan: an organization at its limit is full whichever
    # door the product arrives through, and one door was answering 201.
    await check_item_quota_async(org_id, db)

    storage = await _ensure_storage_async(db, item_in, org_id)
    category = await _ensure_category_async(db, item_in.category_id, org_id)
    if item_in.serial_number:
        await _ensure_serial_unique_async(db, org_id, item_in.serial_number)
    item_data = keyed_by_column(item_in.model_dump(exclude_unset=True))
    if 'metadata' in item_data:
        item_data['meta_data'] = item_data.pop('metadata')
    # An added_date nobody named is the record's birth day — the column
    # default — not a NULL: the core DTO carries the field on every call,
    # so a None here means "not said" and must leave the payload for the
    # column's default to fire (the column is NOT NULL).
    if item_data.get('added_date') is None:
        item_data.pop('added_date', None)

    # Route legacy top-level date fields (freeze_date) into meta_data namespaces.
    from app.services.items._date_meta import fold_legacy_dates_into_meta

    fold_legacy_dates_into_meta(item_data)

    # Validate custom field values against the category's field_definitions
    # (money / multi-select / select value-shape contract).
    await _validate_metadata_against_category_async(db, item_data)

    template, template_created = await resolve_template_for_create_async(
        db, item_in, item_data, org_id
    )

    await place_product_code_async(
        db,
        org_id,
        item_data,
        template,
        card_named=item_in.template_id is not None,
    )

    context = build_module_context(db, org_id, user)
    item_data = await interceptor_pipeline.run_before_item_create(item_data, context)

    #: The unit the matched template keeps, before this call can change it.
    #: Read here because the minting branch below writes the record's unit
    #: onto a template it just created, and the confirmation is about the
    #: template the caller matched, not the one this request leaves behind.
    matched_template_uom_id = template.uom_id

    # The unit is settled before the quantity is measured, so the gate reads
    # the unit this row will land with — the caller's, the matched template's,
    # else pieces. The other order let the default land after the gate: 2.5
    # entered here as "2.5 pieces" while the same 2.5 with ``uom_id: pcs``
    # came back 400, and the only difference between the two requests was a
    # field nobody filled.
    await _resolve_record_unit_async(db, org_id, item_data, template)
    # The gate measures the number the caller named, not the store's three
    # places: a kilogram keeps three too, so 1.1234 would arrive as 1.123 —
    # a number it can hold — and be written without a word.
    await _validate_quantity_precision_async(
        db, {**item_data, 'quantity': item_in.quantity_as_named}
    )

    # The matched template's unit is the reference (AGENTS.md §4): a record
    # landing in another one is a deliberate choice that has to be confirmed.
    # The comparison comes after the hooks, so it sees the unit the row will
    # land with however it was named — request, interceptor or module — and
    # against the template the caller matched, read before the minting branch
    # below writes this record's unit onto a row it just created.
    confirmed_unit = _take_unit_confirmation(item_data) or unit_confirmed_over_template
    chosen_uom_id, entered_quantity = await _settle_unit_choice_async(
        db, item_data, template, matched_template_uom_id, confirmed=confirmed_unit
    )

    if template_created and template.uom_id is None:
        # The catalogue row minted by this call inherits the unit its first
        # record landed with: a template without a unit is the same "a
        # quantity of what" hole one shelf lower, and BoM lines written in
        # any other unit would slip past the convertibility guard that only
        # sees the template. A matched template keeps whatever it has.
        template.uom_id = item_data['uom_id']
        db.add(template)

    # The batch and owner are the caller's to say — a receipt that named a
    # batch — and they are on the row before the posting writes its
    # movement, so the movement names the record's own batch.
    final_data = {
        k: v for k, v in item_data.items() if k in Item.__table__.columns.keys()
    } | {'lot_id': lot_id, 'owner_id': owner_id}
    item = Item(**final_data)
    item.organization_id = org_id
    item.module_name = resolve_module_owner(item.meta_data)
    if label_code is not None:
        item.label_code = label_code

    org_currency = await _resolve_org_currency_async(db, org_id)
    _ensure_item_currency_sync(item, org_currency)

    await _lock_record_group_async(db, org_id, item)
    db.add(item)
    await db.flush()
    await read_back_a_new_record(
        db, item, storage=storage, category=category, template=template
    )

    if post_the_change:
        await _create_stock_entry_async(db, item, user.id)

    await log_action_async(
        db,
        organization_id=org_id,
        user_id=user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        # What the record came into the world with: the journal's Detail
        # column reads this, so "with what" survives the moment it was true.
        # The shelf and the category are named beside their ids — both rows
        # were read a moment ago, and an id is not a place a reader can look.
        snapshot={
            'name': item.name,
            'brand': item.brand,
            'barcode': item.barcode,
            'sku': template.sku,
            'quantity': quantise(item.quantity or Decimal('0'), 3),
            'storage_location_id': str(item.storage_location_id)
            if item.storage_location_id
            else None,
            'storage_location_name': storage.name,
            'category_id': str(item.category_id) if item.category_id else None,
            'category_name': category.name if category is not None else None,
            # The code beside the name, so the reader can say the word the
            # product screen says: a seeded category carries its seed's
            # English (`Dairy`) while the app reads it by code (`Nabiał`).
            'category_code': category.code if category is not None else None,
        },
    )

    # The confirmed choice is written down beside the creation it belongs to:
    # a quantity typed in a unit its product is not kept in is exactly the
    # kind of answer the history exists to give, and the row that says it is
    # the one a reader lands on from the record.
    if confirmed_unit:
        await log_unit_chosen_over_template_async(
            db,
            item,
            history_action,
            template_uom_id=matched_template_uom_id,
            chosen_uom_id=chosen_uom_id,
            entered_quantity=entered_quantity,
            user_id=user.id,
        )

    await _log_item_created_async(
        db, item, user, source_document_id, history_changes, history_action
    )

    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_CREATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(org_id),
                'item': item,
                'user_id': str(user.id),
            }
        ),
    )

    await settle_category(db, item)

    await interceptor_pipeline.run_after_item_create(item.id, item_data, context)
    return item


def _ensure_item_currency_sync(item: Item, org_currency: str | None) -> None:
    if item.currency and org_currency:
        if item.currency != org_currency:
            raise ServiceRejectionError(
                'item_currency_mismatch',
                item_currency=item.currency,
                organization_currency=org_currency,
            )
        return
    if not item.currency and org_currency:
        item.currency = org_currency
    elif not item.currency:
        raise ServiceRejectionError('organization_currency_missing')
