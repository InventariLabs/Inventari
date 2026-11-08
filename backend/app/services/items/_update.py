from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import ModuleContext, build_module_context
from app.core.contracts import UserContextDTO
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import ServiceRejectionError
from app.core.interceptors import interceptor_pipeline
from app.core.logging import get_logger
from app.core.money import quantise
from app.core.posting_batch import current_batch
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.schemas._common import keyed_by_column
from app.schemas.item import ItemQuantityUpdate, ItemUpdate, _take_unit_confirmation
from app.services.audit_service import audit_key, audit_value, log_action_async

from ._loaded import settle_category
from ._module_owner import resolve_module_owner
from ._product_code import place_edited_product_code_async
from ._stock_quant import (
    adopt_card_with_opening_async,
    apply_quantity_change_async,
    lock_record_stock_async,
)
from ._stock_relocation import carry_record_stock_async, lock_shelf_change_async
from ._template import refuse_a_shared_strategy_change, refuse_sku_in_use_async
from ._unit_choice import (
    keep_in_card_unit_async,
    log_unit_chosen_over_template_async,
    refuse_unconfirmed_unit_difference_async,
)
from .history import log_history_async

logger = get_logger(__name__)


async def update_item(
    db: AsyncSession, item: Item, item_in: ItemUpdate, user: UserContextDTO
) -> Item:
    """Update item dynamically."""
    update_data = keyed_by_column(item_in.model_dump(exclude_unset=True))

    await _validate_uniqueness(db, item, update_data, user)
    # Same guard as on create — a re-categorisation must not point at
    # another organization's category.
    if 'category_id' in update_data and user.organization_id is not None:
        from ._create import _ensure_category_async

        await _ensure_category_async(
            db, update_data['category_id'], user.organization_id
        )
    # And the unit is checked for the same reason as on create: the record's
    # response embeds the unit definition, so an unchecked uom_id read
    # another organization's unit and ran conversions on its factor.
    if update_data.get('uom_id') and user.organization_id is not None:
        from ._create import _ensure_uom_async

        await _ensure_uom_async(db, update_data['uom_id'], user.organization_id)
    # And the same guard for the column that decides who can see the record
    # at all: the list and the detail fetch are both scoped by the locations
    # the caller owns, so an unchecked storage_location_id handed the record
    # to another organization — and the stock it holds with it.
    if 'storage_location_id' in update_data and user.organization_id is not None:
        from ._create import _ensure_storage_location_async

        await _ensure_storage_location_async(
            db, update_data['storage_location_id'], user.organization_id
        )
    context = _build_context(db, user)
    update_data = await _run_before_interceptors(item.id, update_data, context)
    _apply_meta_data(item, update_data)
    # The confirmation is spent before anything is applied: it has no column
    # to land in, and the unit guard below is the only reader of it.
    confirmed_unit = _take_unit_confirmation(update_data)
    await _validate_custom_fields(db, item, update_data)
    template_uom_id = await _validate_quantity_and_currency(
        db,
        item,
        update_data,
        user,
        confirmed=confirmed_unit,
        quantity_as_named=item_in.quantity_as_named,
    )
    chosen_uom_id = update_data.get('uom_id')
    entered_quantity = update_data.get('quantity')
    await keep_record_in_card_unit_async(db, item, update_data, template_uom_id)
    # The number the delta is measured from is read under the lock, the same
    # rule the scan path follows: two edits of one record both read the old
    # number before either locked, so each posted its delta against it — the
    # second against a number somebody had already replaced. The shelf lock
    # comes first when the shelf moves, both groups in the one order every
    # multi-group writer shares; the snapshot below is then taken under the
    # record's own stock lock, and the bridge trusts it. A shelf-only edit is
    # a read-modify-write too — the holding it carries off the old shelf is
    # the one the caller fetched — so it takes that lock as well: two moves
    # that fetched the record from one shelf each carried the same holding
    # off it, and the shelf both left was short by the whole holding while
    # the record stood on only one of their destinations.
    if 'storage_location_id' in update_data:
        await lock_shelf_change_async(db, [item], update_data['storage_location_id'])
    if 'quantity' in update_data or 'storage_location_id' in update_data:
        await lock_record_stock_async(db, item)
    code_change = (
        await place_edited_product_code_async(
            db, user.organization_id, item, update_data
        )
        if user.organization_id is not None
        else {}
    )
    old_values = _capture_old_values(item, update_data)
    old_location_id, old_quantity = item.storage_location_id, item.quantity
    _apply_field_updates(item, update_data)
    # The stock goes to the new shelf first, as the record held it there,
    # and a quantity changed in the same request is then posted where the
    # record now stands — the order a person would do it in, and the only
    # one in which the old shelf gives up everything it held.
    await carry_record_stock_async(
        db,
        item,
        from_location_id=old_location_id,
        quantity=old_quantity,
        user_id=user.id,
    )
    await _handle_quantity_change(db, item, update_data, old_values, user)
    # Ownership follows the namespaces the record actually carries, so a
    # module namespace added or dropped by this update is reflected rather
    # than frozen at whatever the record was created as.
    item.module_name = resolve_module_owner(item.meta_data)
    # The confirmed unit choice is written down beside the edit it belongs
    # to, in the same shape the create path writes it: "who typed this in a
    # unit its product is not kept in" is the question the row answers.
    if confirmed_unit and template_uom_id is not None:
        await log_unit_chosen_over_template_async(
            db,
            item,
            ItemAction.UPDATED,
            template_uom_id=template_uom_id,
            chosen_uom_id=chosen_uom_id,
            entered_quantity=entered_quantity,
            user_id=user.id,
        )
    template_changes = code_change | await _sync_template_fields(
        db, item, update_data, user
    )
    await _log_and_emit(
        db, item, update_data, old_values, template_changes, user, context
    )
    return item


async def _validate_uniqueness(
    db: AsyncSession, item: Item, update_data: dict[str, Any], user: UserContextDTO
) -> None:
    """Reject serial_number/barcode collisions before applying the update."""
    if (
        'serial_number' in update_data
        and update_data['serial_number']
        and update_data['serial_number'].strip()
        and update_data['serial_number'] != item.serial_number
    ):
        from ._create import _ensure_serial_unique_async

        if user.organization_id is not None:
            await _ensure_serial_unique_async(
                db,
                user.organization_id,
                update_data['serial_number'],
                exclude_item_id=item.id,
            )

    # Mirror the serial_number uniqueness check for barcode. Without it,
    # updating an item's barcode to one already used in the org silently
    # succeeds (until a unique index would reject it at the DB).
    if (
        user.organization_id is not None
        and 'barcode' in update_data
        and update_data['barcode']
        and update_data['barcode'] != item.barcode
    ):
        from ._create import _ensure_barcode_unique_async

        await _ensure_barcode_unique_async(
            db,
            user.organization_id,
            update_data['barcode'],
            exclude_item_id=item.id,
        )


def _build_context(db: AsyncSession, user: UserContextDTO) -> ModuleContext:
    """Build the interceptor module context for this request."""
    return build_module_context(db, user.organization_id, user)


async def _run_before_interceptors(
    item_id: UUID, update_data: dict[str, Any], context: ModuleContext
) -> dict[str, Any]:
    """Run the before_item_update interceptor hook."""
    return await interceptor_pipeline.run_before_item_update(
        item_id, update_data, context
    )


def _apply_meta_data(item: Item, update_data: dict[str, Any]) -> None:
    """Normalize legacy metadata keys (metadata -> meta_data, freeze_date)."""
    if 'metadata' in update_data:
        update_data['meta_data'] = update_data.pop('metadata')

    # Route legacy top-level date fields (freeze_date) into meta_data, merging
    # with existing meta_data so other namespaces are preserved.
    if 'freeze_date' in update_data:
        from app.services.items._date_meta import merge_legacy_date_into_meta

        item.meta_data = merge_legacy_date_into_meta(
            item.meta_data, 'freeze_date', update_data.pop('freeze_date')
        )


async def _validate_custom_fields(
    db: AsyncSession, item: Item, update_data: dict[str, Any]
) -> None:
    """Validate custom field values against the category's field_definitions."""
    # Validate custom field values against the category's field_definitions
    # Category may change in the same update, so resolve
    # the effective category_id from update_data or fall back to the item's
    # existing category.
    effective_category_id = update_data.get('category_id') or item.category_id
    if update_data.get('meta_data') and effective_category_id:
        from app.models.category import Category
        from app.services.fields.validation import validate_item_metadata_fields

        category = await db.get(Category, effective_category_id)
        if category is not None:
            validate_item_metadata_fields(
                update_data['meta_data'], category.field_definitions
            )


async def _refuse_unit_removal(
    db: AsyncSession, item: Item, update_data: dict[str, Any]
) -> None:
    """Refuse an edit that would leave the record without a unit.

    Both create doors answer "a quantity of what" for the caller — the
    template's unit, else pieces — and ``{"uom_id": null}`` undid that in one
    request. Swapping in pieces instead would relabel the stock, which the
    guard below forbids, so the honest answer is a refusal. A record that
    already has no unit is not refused for saying so again: nothing is taken.
    """
    if 'uom_id' not in update_data or update_data['uom_id'] is not None:
        return
    if item.uom_id is None:
        return

    from app.services.uom_service import get_uom_async

    current = await get_uom_async(db, item.uom_id)
    raise ServiceRejectionError(
        'item_unit_cannot_be_removed',
        unit=current.symbol if current else str(item.uom_id),
    )


async def _refuse_unit_swap_under_stock(
    db: AsyncSession, item: Item, update_data: dict[str, Any]
) -> None:
    """Refuse a unit change on a record that holds stock.

    ``uom_id`` used to be applied like any other field, so "5 pcs" became
    "5 kg" without conversion, without refusal and without a readable trace:
    the history logged a pair of UUIDs and no symbols. The number on the
    shelf did not change, so the unit under it must not either — Odoo blocks
    the same edit on a product with stock or movements, and this is that
    rule. An empty record is free to change its mind.
    """
    new_uom_id = update_data.get('uom_id')
    if new_uom_id is None or new_uom_id == item.uom_id:
        return
    if not item.quantity or item.quantity <= 0:
        return

    from app.services.uom_service import get_uom_async

    current = await get_uom_async(db, item.uom_id) if item.uom_id else None
    incoming = await get_uom_async(db, new_uom_id)
    raise ServiceRejectionError(
        'item_unit_change_blocked_by_stock',
        current_unit=current.symbol if current else '—',
        new_unit=incoming.symbol if incoming else str(new_uom_id),
        quantity=item.quantity,
    )


async def keep_record_in_card_unit_async(
    db: AsyncSession,
    item: Item,
    update_data: dict[str, Any],
    template_uom_id: UUID | None,
) -> None:
    """Restate an edit that names another unit in the record's card's unit.

    *template_uom_id* is what ``_validate_quantity_and_currency`` answers:
    the card's unit when the edit moves the record's unit, else ``None``.
    The stock guard lets only an empty record's unit move, so the quantity
    to restate is the one the edit names, and the record stays in its
    card's unit — the edit and the create keep one rule, in
    ``keep_in_card_unit_async``.
    """
    if template_uom_id is None or item.template_id is None:
        return
    card = await db.get(ProductTemplate, item.template_id)
    await keep_in_card_unit_async(db, update_data, card, product_name=item.name)


async def _matched_template_uom_id_async(db: AsyncSession, item: Item) -> UUID | None:
    """The unit this record's product template keeps — its reference unit.

    ``None`` for a record without a template: no catalogue row, no claim to
    contradict, and nothing to confirm. A template with no unit of its own
    reads the same way, and the piece default is what decides there.
    """
    if item.template_id is None:
        return None
    return await db.scalar(
        select(ProductTemplate.uom_id).where(ProductTemplate.id == item.template_id)
    )


async def _validate_quantity_and_currency(
    db: AsyncSession,
    item: Item,
    update_data: dict[str, Any],
    user: UserContextDTO,
    *,
    confirmed: bool = False,
    quantity_as_named: Decimal | None = None,
) -> UUID | None:
    """Enforce UoM quantity precision and org currency match.

    Returns the matched template's unit when this update names a unit of its
    own, so the caller can record a confirmed choice without reading the
    template a second time. ``None`` says the record's unit did not move.
    """
    await _refuse_unit_removal(db, item, update_data)
    await _refuse_unit_swap_under_stock(db, item, update_data)

    template_uom_id: UUID | None = None
    new_uom_id = update_data.get('uom_id')
    if new_uom_id is not None and new_uom_id != item.uom_id:
        # The same rule as on create (AGENTS.md §4): the product's template
        # says which unit this record is kept in, and moving it elsewhere is
        # a choice its caller has to confirm. The stock guard above still
        # answers first — a record holding stock never gets here at all.
        template_uom_id = await _matched_template_uom_id_async(db, item)
        await refuse_unconfirmed_unit_difference_async(
            db,
            template_uom_id=template_uom_id,
            chosen_uom_id=new_uom_id,
            product_name=item.name,
            confirmed=confirmed,
        )

    effective_uom_id = update_data.get('uom_id') or item.uom_id
    # The quantity the unit will describe: the one in this request, or the
    # one already on the record. Reading only the request meant a unit that
    # forbids fractions could be set under a fractional quantity as long as
    # the two arrived in separate calls.
    # The request's quantity is measured as named, before the schema's three
    # places, the same way the create door measures it.
    effective_quantity = (
        quantity_as_named
        if 'quantity' in update_data and update_data['quantity'] is not None
        else item.quantity
    )
    if effective_uom_id and effective_quantity is not None:
        from app.services.uom_service import validate_quantity_precision_async

        await validate_quantity_precision_async(
            db, effective_uom_id, Decimal(str(effective_quantity))
        )

    new_currency = update_data.get('currency')
    if new_currency:
        org_currency = await db.scalar(
            select(Organization.currency).where(Organization.id == user.organization_id)
        )
        if org_currency and new_currency != org_currency:
            raise ServiceRejectionError(
                'item_currency_mismatch',
                item_currency=new_currency,
                organization_currency=org_currency,
            )

    return template_uom_id


# The pair this module's journal keys come from: `_capture_old_values` builds
# its `before` from the update payload, so every key it can write is a field
# the schema and the model share. The snapshot-key exporter reads this
# declaration (backend/scripts/export_audit_snapshot_keys.py); a writer of
# the same shape declares its own pair beside its own loop.
AUDIT_PAYLOAD_SCHEMA = ('ItemUpdate', 'Item')


def _capture_old_values(item: Item, update_data: dict[str, Any]) -> dict[str, Any]:
    """Snapshot pre-update attribute values for history/audit."""
    return {k: getattr(item, k) for k in update_data.keys() if hasattr(item, k)}


def _apply_field_updates(item: Item, update_data: dict[str, Any]) -> None:
    """Set updated fields on the item (min_quantity is handled separately)."""
    _sentinel = object()
    min_quantity_value = update_data.pop('min_quantity', _sentinel)
    min_quantity_present = min_quantity_value is not _sentinel

    for field, value in update_data.items():
        if hasattr(item, field):
            setattr(item, field, value)

    if min_quantity_present:
        update_data['min_quantity'] = min_quantity_value


async def _handle_quantity_change(
    db: AsyncSession,
    item: Item,
    update_data: dict[str, Any],
    old_values: dict[str, Any],
    user: UserContextDTO,
) -> None:
    """Apply quantity changes through the stock-quant sync path."""
    if 'quantity' in old_values and 'quantity' in update_data:
        old_qty = old_values.get('quantity')
        new_qty = update_data['quantity']
        if old_qty != new_qty:
            await apply_quantity_change_async(
                db, item, new_qty, old_quantity=old_qty, user_id=user.id
            )


#: Fields that describe the *product*, not this row of stock: the low-stock
#: threshold, the weight of a single unit (ADR-015) and the order its stock
#: leaves in. They travel on the item payload but are written to its template.
_AUDITED_TEMPLATE_FIELDS = (
    'min_quantity',
    'weight_value',
    'weight_uom_id',
    'removal_strategy',
    'sku',
)


def _coerce_template_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field == 'min_quantity':
        # A DOUBLE PRECISION column: the float is what it keeps.
        return float(value)
    if field == 'weight_value':
        # NUMERIC(14, 6): the journal records the digits the column holds.
        return quantise(Decimal(str(value)), 6)
    return value


async def _sync_template_fields(
    db: AsyncSession, item: Item, update_data: dict[str, Any], user: UserContextDTO
) -> dict[str, tuple[Any, Any]]:
    """Write product-level fields to the item's org-owned template.

    A record with no template gets one when there is something to record on
    it, and gets it the way every other door gives one: resolved or minted
    from the record's own words and bound with its paper, the stock the
    record holds posted as an opening. Returns the fields that actually
    moved, so that a change to the unit weight or the low-stock threshold is
    not the one kind of edit the audit log stays silent about — these keys
    leave ``update_data`` here, and everything downstream reads them from
    the return value instead.
    """
    present = {k: update_data[k] for k in _AUDITED_TEMPLATE_FIELDS if k in update_data}
    if not present:
        return {}
    for field in present:
        del update_data[field]

    values = {k: _coerce_template_value(k, v) for k, v in present.items()}
    if item.template_id is None:
        if all(v is None for v in values.values()):
            return {}
        # This door used to mint the card itself: a twin beside any card of
        # the same name, bound with no paper, and the stock the record held
        # left outside the register it had just joined — the record said 4
        # and its shelf said nothing. The adoption the record's posting runs carries
        # the record's unit onto a minted card (pieces for a record older
        # than the default) and posts the holding; a quantity changed in the
        # same request has already been through it.
        await adopt_card_with_opening_async(
            db, item, holding=item.quantity or Decimal('0'), user_id=user.id
        )

    # Only mutate a template owned by this org. A global/shared template
    # (organization_id IS NULL) must never be written here — doing so would
    # change the threshold or unit weight for every org. Updates on
    # global-template items are a no-op.
    result = await db.scalars(
        select(ProductTemplate).where(
            ProductTemplate.id == item.template_id,
            ProductTemplate.organization_id == user.organization_id,
        ),
    )
    template = cast('ProductTemplate | None', result.first())
    if template is None and item.template_id and 'removal_strategy' in values:
        refuse_a_shared_strategy_change(
            await db.scalar(
                select(ProductTemplate.removal_strategy).where(
                    ProductTemplate.id == item.template_id
                )
            ),
            values['removal_strategy'],
        )
    changed: dict[str, tuple[Any, Any]] = {}
    if template:
        if (
            values.get('sku')
            and values['sku'] != template.sku
            and user.organization_id is not None
        ):
            await refuse_sku_in_use_async(
                db, user.organization_id, values['sku'], except_template_id=template.id
            )
        for field, value in values.items():
            before = getattr(template, field, None)
            if audit_key(before) != audit_key(value):
                changed[field] = (audit_value(before), audit_value(value))
            setattr(template, field, value)
        db.add(template)
    return changed


def _changed_fields(
    old_values: dict[str, Any], update_data: dict[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """The fields whose value actually moved, as ``field: (before, after)``.

    The form posts its whole state, not the fields somebody touched, so the
    payload is not a change and must not be logged as one. A key the item does
    not carry never reaches the record either (``_apply_field_updates`` skips
    it), so it is not a change of anything.
    """
    changed: dict[str, tuple[Any, Any]] = {}
    for field, new_value in update_data.items():
        if field not in old_values:
            continue
        if audit_key(old_values[field]) != audit_key(new_value):
            changed[field] = (
                audit_value(old_values[field]),
                audit_value(new_value),
            )
    return changed


#: The item's columns that point at another record, the table behind each one,
#: and the attribute a reader knows that record by. A journal line saying
#: ``Location: 67d57628`` is eight characters of a UUID the reader can do
#: nothing with — not even paste into a search.
_REFERENCE_MODELS: dict[str, tuple[Any, str]] = {
    'storage_location_id': (StorageLocation, 'name'),
    'category_id': (Category, 'name'),
    'template_id': (ProductTemplate, 'name'),
    # The organization a purge row outlives the record for: the journal is
    # read months later, and the entry kept nothing but the id.
    'organization_id': (Organization, 'name'),
    # A unit is read by its symbol — `kg`, the word the product screen and the
    # shelf label print — never by its `name` (`Kilogram`), which no screen
    # shows.
    'uom_id': (Uom, 'symbol'),
    # The piece weight names its unit by the same symbol — `g` beside the
    # weight the card carries, the word the product screen and the shelf
    # label print. Without it the journal read `Weight uom: — → ac76d1cb`.
    'weight_uom_id': (Uom, 'symbol'),
}

#: The references whose reader-facing word the app resolves from a code, and
#: the column that code sits in. A seeded category is named by its seed in
#: English (`Dairy`) while every screen shows the label its code translates
#: to (`Nabiał`) — one category, one name. The code travels beside the name so
#: the journal can say the word the product screen says.
_REFERENCE_CODES: dict[str, str] = {'category_id': 'code'}


async def _reference_names(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    """The name of every reference in *values*, read in this transaction.

    The name goes into the snapshot beside the id rather than being looked up
    when the journal is read: the storage location is renamed next week and
    the journal is the record of what it was called when the change was made.
    The row is already in the session whenever this update validated the id it
    points at, so naming it usually costs no query at all. A reference the app
    reads by code carries the code too, so the reader can resolve the same
    word every other screen shows.
    """
    names: dict[str, Any] = {}
    for field, value in values.items():
        entry = _REFERENCE_MODELS.get(field)
        if entry is None or value is None:
            continue
        model, attribute = entry
        record = await db.get(model, value)
        if record is None:
            continue
        base = field.removesuffix('_id')
        names[f'{base}_name'] = getattr(record, attribute, None)
        code_field = _REFERENCE_CODES.get(field)
        code = getattr(record, code_field, None) if code_field else None
        if code:
            names[f'{base}_code'] = code
    return names


async def _log_and_emit(
    db: AsyncSession,
    item: Item,
    update_data: dict[str, Any],
    old_values: dict[str, Any],
    template_changes: dict[str, tuple[Any, Any]],
    user: UserContextDTO,
    context: ModuleContext,
) -> None:
    """Persist, record history/audit, emit the update event, run after hooks."""
    await db.flush()
    changed = _changed_fields(old_values, update_data) | template_changes
    # The names of the records this entry points at, each beside the id it
    # belongs to: which shelf the goods left and which one they arrived on
    # is the answer the reader came for, and the ids are not it.
    # The names name the ids the entry carries, side by side. A template
    # field left ``update_data`` when it was written to the card, so its
    # id is only in the pair ``changed`` holds — reading the name from
    # the payload alone left that side unnamed.
    before = {field: before for field, (before, _) in changed.items()} | (
        await _reference_names(
            db, {f: old_values.get(f, changed[f][0]) for f in changed}
        )
    )
    after = {field: after for field, (_, after) in changed.items()} | (
        await _reference_names(
            db, {f: update_data.get(f, changed[f][1]) for f in changed}
        )
    )
    # The card's own history carries the names too. It used to keep the ids
    # alone, so one event read `Category: ffb4a9cd → 7ab33755` on the card
    # while the journal beside it spelled the words.
    await log_history_async(
        db,
        item,
        ItemAction.UPDATED,
        {
            'old': {**old_values, **before},
            'new': {**update_data, **after},
        },
        user_id=user.id,
    )
    # An update that changed nothing is not an event. Logging it anyway is how
    # the log filled up with entries whose every field read `x → x`, and a log
    # nobody can read for the change they are looking for is not a record.
    if changed:
        await log_action_async(
            db,
            organization_id=item.organization_id,
            user_id=user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.ITEM,
            target_id=item.id,
            snapshot={
                # Which record this is about. Every other entry says so, the
                # bulk edit next door says so, and without it the journal's
                # Target column falls back to eight characters of the id.
                'name': item.name,
                'before': before,
                'after': after,
                'fields': list(changed),
            },
        )
    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'item': item,
                'changes': update_data,
                'user_id': str(user.id),
            }
        ),
    )
    # The answer is the row after the write: a changed ``uom_id`` does not
    # reload the ``uom`` loaded with the record, so the response named the
    # unit the edit had just replaced.
    await db.refresh(item, ['category', 'template', 'uom'])
    await interceptor_pipeline.run_after_item_update(item.id, update_data, context)


async def update_quantity(
    db: AsyncSession,
    item: Item,
    quantity_update: ItemQuantityUpdate,
    user_id: UUID | None = None,
    source_document_id: UUID | None = None,
    history_changes: dict[str, Any] | None = None,
    sync_valuation: bool = True,
    post_the_change: bool = True,
    lot_id: UUID | None = None,
    move_reference_type: str = 'item',
    move_reference_id: UUID | None = None,
) -> Item:
    from app.core.period_guard import check_period_not_closed
    from app.services.analytics._common import org_today_async

    # Inventory period lock. Which day it is decides whether the edit passes
    # at all, so it is the organization's day, not the server's — a
    # warehouse in Auckland was being told the month had closed at 11am.
    if item.organization_id is not None:
        await check_period_not_closed(
            db,
            item.organization_id,
            await org_today_async(db, item.organization_id),
        )

    changes = {'quantity': float(quantity_update.quantity)}

    context = build_module_context(db, item.organization_id, None)
    await interceptor_pipeline.run_before_item_update(item.id, changes, context)

    if lot_id is not None and item.lot_id is None:
        # A caller that names the batch looked at the goods — a count did.
        # A record that names none learns which batch it holds; one that
        # names another keeps it, and the named batch takes only the change.
        item.lot_id = lot_id

    old_quantity = await apply_quantity_change_async(
        db,
        item,
        quantity_update.quantity,
        sync_valuation=sync_valuation,
        post_the_change=post_the_change,
        lot_id=lot_id,
        move_reference_type=move_reference_type,
        move_reference_id=move_reference_id,
        user_id=user_id,
    )
    if current_batch(db) is None:
        # Inside a posting the records are written with the next statement
        # that reads them, or with the end of the posting, as one set.
        await db.flush()
    await log_history_async(
        db,
        item,
        ItemAction.QUANTITY_CHANGED,
        {
            # The audit trail carries the exact Decimals as strings: a float
            # here is less precise than the data it describes.
            'old': str(old_quantity) if old_quantity is not None else '0',
            'new': str(item.quantity),
            **(history_changes or {}),
        },
        user_id=user_id,
        source_document_id=source_document_id,
    )
    # The caller's ``history_changes`` already says why the quantity moved and
    # what it came from; the organization log used to get neither, so a
    # correction from a stock take was indistinguishable from a manual edit.
    audit_extras = dict(history_changes or {})
    audit_reason = audit_extras.pop('reason', None)
    # The history row has carried this since it was written; the log row did
    # not, so "which document moved this" was answerable for one product at a
    # time and never from the screen that shows the whole organization.
    if source_document_id is not None:
        audit_extras['source_document_id'] = str(source_document_id)
    await log_action_async(
        db,
        organization_id=item.organization_id,
        user_id=user_id,
        action=AuditAction.QUANTITY_CHANGE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': {
                'quantity': (str(old_quantity) if old_quantity is not None else '0')
            },
            'after': {'quantity': str(item.quantity)},
        },
        reason=audit_reason,
        meta_data=audit_extras or None,
    )
    await event_bus.emit_transactional(
        db,
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(item.organization_id),
                'item': item,
                'changes': {'quantity': float(item.quantity)},
                'user_id': str(user_id) if user_id else None,
            }
        ),
    )
    await settle_category(db, item)
    await interceptor_pipeline.run_after_item_update(item.id, changes, context)
    return item
