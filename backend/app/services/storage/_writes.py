from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.interceptors import interceptor_pipeline
from app.i18n.service import get_current_lang, get_error_message
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.label_pool import LabelPool
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import StorageType
from app.schemas._common import keyed_by_column
from app.schemas.storage_location import (
    StorageArchiveRequest,
    StorageLocationCreate,
    StorageLocationUpdate,
)
from app.services.audit_service import audit_key, audit_value, log_action_async
from app.services.storage._codes import code_for_new_location_async
from app.services.storage._queries import (
    is_descendant_async,
    locations_holding_stock_async,
)
from app.services.storage._relocation import record_moved_location_async


def _org_id(user: UserContextDTO) -> UUID:
    """The caller's organization, asserted — every write path here has
    already refused to run without one."""
    assert user.organization_id is not None
    return user.organization_id


async def _get_parent_in_org(
    db: AsyncSession, organization_id, parent_id
) -> StorageLocation:
    """Fetch the parent in the same organization or raise 404."""
    parent = await db.scalar(
        select(StorageLocation).where(
            StorageLocation.id == parent_id,
            StorageLocation.organization_id == organization_id,
        )
    )
    if parent is None:
        raise NotFoundException('storage')
    return parent


async def _validate_parent_id(
    db: AsyncSession,
    organization_id,
    storage_id,
    parent_id,
) -> StorageLocation | None:
    """Validate a storage location's new parent and return it.

    Checks, in order:
    - the parent exists and belongs to the same organization (404),
    - the parent is not the edited node itself (400),
    - the parent is not a descendant of the edited node (409 STORAGE_CYCLE).
    """
    if parent_id is None:
        return None
    if storage_id is not None and parent_id == storage_id:
        raise catalogue_refusal('storage_own_parent')
    parent = await _get_parent_in_org(db, organization_id, parent_id)
    if storage_id is not None and await is_descendant_async(
        db, organization_id, storage_id, parent_id
    ):
        raise ConflictException(
            code='STORAGE_CYCLE',
            message=get_error_message('storage_would_cycle', get_current_lang()),
        )
    return parent


async def _parent_name(db: AsyncSession, organization_id, parent_id) -> str | None:
    """The name of the location above this one, or ``None`` when there is none.

    ``Parent: 67d57628`` is eight characters of a UUID, which is not an answer
    to "where did this go". Read here, in the same transaction as the write:
    the parent is renamed later, and the journal is the record of what it was
    called when the change was made. A row the caller has already read for
    validation is in the session, so naming it costs no second query.
    """
    if parent_id is None:
        return None
    parent = await db.get(StorageLocation, parent_id)
    if parent is None or parent.organization_id != organization_id:
        return None
    return parent.name


async def _storage_type_name(db: AsyncSession, storage_type_id) -> str | None:
    """The kind of place this is, or ``None`` when it has no type.

    ``Storage type: 4a2e2c4b`` is the same eight characters of a UUID as the
    parent line beside it, read the same way and for the same reason: the type
    is renamed later, and the journal says what it was called when the change
    was made. Not scoped to the organization — the seeded system types carry
    none, and every organization is meant to use them.
    """
    if storage_type_id is None:
        return None
    storage_type = await db.get(StorageType, storage_type_id)
    return storage_type.name if storage_type is not None else None


#: The two unique indexes behind the sibling-name rule (the model declares
#: them): one for the places under a parent, one for the top level.
_NAME_INDEXES = (
    'uq_storage_locations_org_parent_name',
    'uq_storage_locations_org_root_name',
)


def _name_taken(name: str) -> ConflictException:
    return ConflictException(
        code='STORAGE_CONFLICT',
        message=get_error_message(
            'storage_name_collision', get_current_lang(), name=name
        ),
    )


@asynccontextmanager
async def _name_rule_held_by_the_database(
    db: AsyncSession, name: str
) -> AsyncIterator[None]:
    """Answer a sibling-name index violation the way the read answers it.

    ``_check_name_unique`` reads before the write, so two requests that both
    read before either wrote each saw a free name; the second insert then
    meets the unique index. That is the same 409 the read gives, not a 500.
    The savepoint keeps the failed statement from poisoning the caller's
    transaction. Any other integrity error is re-raised untouched.
    """
    try:
        async with db.begin_nested():
            yield
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
        if constraint in _NAME_INDEXES or any(
            index in str(exc.orig) for index in _NAME_INDEXES
        ):
            raise _name_taken(name) from exc
        raise


async def _flush_under_the_name_rule(db: AsyncSession, name: str) -> None:
    async with _name_rule_held_by_the_database(db, name):
        await db.flush()


async def _check_name_unique(
    db: AsyncSession,
    organization_id,
    name: str,
    parent_id=None,
    exclude_id=None,
) -> None:
    """Raise 409 if a sibling with the same name already exists.

    Typed here rather than left to the endpoint. The same collision used to
    surface as 400 from create, 409 from update and 400 from the hierarchy
    builder, because each endpoint mapped one bare ``ValueError`` its own way
    — so a client wanting to tell "bad name" from "name taken" had to read
    the English sentence, which is exactly what the copy gate forbids.
    """
    query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        StorageLocation.name == name,
        StorageLocation.parent_id == parent_id,
    )
    if exclude_id is not None:
        query = query.where(StorageLocation.id != exclude_id)
    result = await db.scalars(query)
    existing = result.first()
    if existing:
        raise _name_taken(name)


async def _check_short_code_unique(
    db: AsyncSession,
    organization_id,
    short_code: str,
    exclude_id=None,
) -> None:
    """Raise if the organization already uses this short code.

    Scoped to the organization on purpose: the check used to span the whole
    table, so a code taken by any tenant was refused to all the others — and
    the refusal message ("another location") confirmed that a row existed
    somewhere the caller cannot see.
    """
    query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        StorageLocation.short_code == short_code,
    )
    if exclude_id is not None:
        query = query.where(StorageLocation.id != exclude_id)
    result = await db.scalars(query)
    # A pool label's code counts too: a renumbered location's old sticker
    # lives on as one, and a new location taking that code would make the
    # old sticker name another shelf.
    label = await db.scalar(
        select(LabelPool.id).where(
            LabelPool.organization_id == organization_id,
            LabelPool.short_code == short_code,
            or_(
                LabelPool.target_storage_location_id.is_(None),
                LabelPool.target_storage_location_id != exclude_id,
            )
            if exclude_id is not None
            else true(),
        )
    )
    if result.first() or label is not None:
        raise ConflictException(
            code='STORAGE_SHORT_CODE_CONFLICT',
            message=get_error_message(
                'storage_short_code_in_use', get_current_lang(), short_code=short_code
            ),
        )


async def _assert_storage_type_available(
    db: AsyncSession, organization_id: UUID, storage_type_id: UUID
) -> None:
    """Mine or global, and nothing else.

    A foreign key is not a tenant boundary: looking the type up by primary
    key alone accepted any UUID in the installation, another organization's
    custom type included. The second half of the condition is equally
    load-bearing -- the seeded system types carry no organization at all,
    and every organization is meant to use them.
    """
    found = await db.scalars(
        select(StorageType).where(
            StorageType.id == storage_type_id,
            or_(
                StorageType.organization_id == organization_id,
                StorageType.organization_id.is_(None),
            ),
        )
    )
    if not found.first():
        raise NotFoundException('storage_type')


async def create_storage(
    db: AsyncSession, storage_in: StorageLocationCreate, user: UserContextDTO
) -> StorageLocation:
    """Create a new storage location after running interceptors."""
    storage_data = keyed_by_column(storage_in.model_dump(exclude_unset=True))

    context = build_module_context(db, user.organization_id, user)

    storage_data = await interceptor_pipeline.run_before_storage_create(
        storage_data, context
    )

    parent_id = storage_data.get('parent_id')
    parent = await _validate_parent_id(db, user.organization_id, None, parent_id)

    # A location whose only address is inside a module's location belongs to
    # that module's world for listing purposes: without the inheritance the
    # child stayed on the general lists its parent dropped out of — an orphan
    # that could not say where it lived. Only an absent tag is filled; one the
    # caller (or an interceptor) set is their claim and always wins.
    if parent is not None and not storage_data.get('context_tag'):
        if parent.context_tag:
            storage_data['context_tag'] = parent.context_tag

    await _check_name_unique(
        db,
        user.organization_id,
        storage_data.get('name', ''),
        parent_id=parent_id,
    )

    if storage_data.get('storage_type_id'):
        await _assert_storage_type_available(
            db, _org_id(user), storage_data['storage_type_id']
        )

    model_columns = StorageLocation.__table__.columns.keys()
    final_data = {k: v for k, v in storage_data.items() if k in model_columns}

    storage = StorageLocation(**final_data)
    storage.organization_id = user.organization_id  # type: ignore[assignment]
    storage.created_by = user.id
    # Anything created through the API is a real place. The virtual
    # counterparts (consumption, loss, production) are seeded per
    # organization straight through the model, so this path never needs to
    # produce one — and a payload or an interceptor cannot smuggle one in.
    storage.usage = LocationUsage.INTERNAL.value
    if storage.short_code:
        # Client-supplied code. Without this the duplicate only surfaces as an
        # IntegrityError from the unique constraint, i.e. a 500 on a request
        # the caller could have been told about.
        await _check_short_code_unique(db, user.organization_id, storage.short_code)
    else:
        storage.short_code = await code_for_new_location_async(
            db, _org_id(user), storage.parent_id, storage_data.get('short_code_prefix')
        )

    async with _name_rule_held_by_the_database(db, storage.name):
        db.add(storage)
        await db.flush()
    await log_action_async(
        db,
        organization_id=_org_id(user),
        user_id=user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.STORAGE,
        target_id=storage.id,
        snapshot={
            'name': storage.name,
            'parent_id': audit_value(storage.parent_id),
            'parent_name': await _parent_name(db, _org_id(user), storage.parent_id),
            'usage': audit_value(storage.usage),
        },
    )
    # The commit is the caller's (request-scoped session, onboarding
    # bundle, hierarchy chain — each owns its unit of work). The refresh
    # stays: the caller reads back what the interceptors may have changed.
    await db.refresh(storage)
    await event_bus.emit_transactional(
        db,
        SystemEvent.STORAGE_CREATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'location_id': str(storage.id),
            }
        ),
    )
    await interceptor_pipeline.run_after_storage_create(
        storage.id, storage_data, context
    )
    return storage


# The pair this module's journal keys come from: the update path builds its
# `before` from the payload (`audited_fields` below), so every key it can
# write is a field the schema and the model share. The snapshot-key exporter
# reads this declaration (backend/scripts/export_audit_snapshot_keys.py); a
# writer of the same shape declares its own pair beside its own loop.
AUDIT_PAYLOAD_SCHEMA = ('StorageLocationUpdate', 'StorageLocation')


async def update_storage(
    db: AsyncSession,
    storage: StorageLocation,
    storage_in: StorageLocationUpdate,
    user: UserContextDTO,
) -> StorageLocation:
    """Update storage location after running interceptors."""
    update_data = keyed_by_column(storage_in.model_dump(exclude_unset=True))
    # What a change of parent means, not a field of the location: see
    # ``StorageLocationUpdate.relocation``.
    relocation = update_data.pop('relocation', None)
    # Judged on the payload as it arrived, before any interceptor rewrites it.
    # Flipping a shelf to a virtual usage takes its contents out of stock,
    # reports, purchase suggestions and scan lookup, and the shelf itself out
    # of the tree it was reached from — so the way back is gone too. Nothing
    # in the app offers the change any more; this is the other bar on the
    # same door.
    if 'usage' in update_data and update_data['usage'] != storage.usage:
        raise catalogue_refusal('storage_usage_immutable', field='usage')

    # The same rule as on create, and it was missing entirely here: the
    # field went from the payload onto the model without so much as an
    # existence check.
    if update_data.get('storage_type_id'):
        await _assert_storage_type_available(
            db, _org_id(user), update_data['storage_type_id']
        )

    context = build_module_context(db, user.organization_id, user)

    update_data = await interceptor_pipeline.run_before_storage_update(
        storage.id, update_data, context
    )

    new_name = update_data.get('name', storage.name)
    new_parent_id = update_data.get('parent_id', storage.parent_id)
    name_changed = 'name' in update_data and update_data['name'] != storage.name
    parent_changed = (
        'parent_id' in update_data and update_data['parent_id'] != storage.parent_id
    )
    if parent_changed:
        # ADR-018: depth is not a reason to refuse a move; parent integrity is.
        new_parent = await _validate_parent_id(
            db, user.organization_id, storage.id, new_parent_id
        )
        # The same inheritance as on create: filing an untagged location into
        # a module's subtree makes it that module's data, or the move would
        # strand it on the general lists its new parent is hidden from. A tag
        # the location already carries is never rewritten by a move.
        if (
            new_parent is not None
            and not storage.context_tag
            and new_parent.context_tag
        ):
            update_data['context_tag'] = new_parent.context_tag
    if name_changed or parent_changed:
        await _check_name_unique(
            db,
            user.organization_id,
            new_name,
            parent_id=new_parent_id,
            exclude_id=storage.id,
        )

    if 'short_code' in update_data and update_data['short_code'] != storage.short_code:
        new_code = update_data['short_code']
        if new_code:
            await _check_short_code_unique(
                db, user.organization_id, new_code, exclude_id=storage.id
            )

    audited_fields = [f for f in update_data if hasattr(storage, f)]
    before = {f: getattr(storage, f) for f in audited_fields}

    for field, value in update_data.items():
        if hasattr(storage, field):
            setattr(storage, field, value)
            if field in ('settings', 'context_schema', 'field_definitions'):
                flag_modified(storage, field)
    await _flush_under_the_name_rule(db, storage.name)

    # A re-filing that changed nothing is not an event — the same rule the
    # item update applies. A change of `usage` is the quiet, org-wide one
    # (a virtual location stops counting into the stock the reader sees),
    # and this entry is the trail it used to leave nowhere.
    after = {f: getattr(storage, f) for f in audited_fields}
    # A list, not a set: the order the fields were audited in decides the
    # order the Detail column prints them, and a set has none — the same
    # entry put its lines in a different order every time the page was
    # opened, and the parent of a move is the line the reader came for.
    changed = [f for f in audited_fields if audit_key(before[f]) != audit_key(after[f])]
    if changed:
        before_values = {f: audit_value(before[f]) for f in changed}
        after_values = {f: audit_value(after[f]) for f in changed}
        # A move is a change of parent, and `parent_id` alone does not say
        # which shelf the location left or which one it landed on. The name
        # goes on the side it belongs to, read before the move is written
        # down: the old parent can be renamed or removed afterwards. The type
        # is the same pair on the same row — `Storage type: 4a2e2c4b` answers
        # no more than `Parent: 67d57628` did.
        organization_id = _org_id(user)
        if 'parent_id' in changed:
            before_values['parent_name'] = await _parent_name(
                db, organization_id, before['parent_id']
            )
            after_values['parent_name'] = await _parent_name(
                db, organization_id, after['parent_id']
            )
        if 'storage_type_id' in changed:
            before_values['storage_type_name'] = await _storage_type_name(
                db, before['storage_type_id']
            )
            after_values['storage_type_name'] = await _storage_type_name(
                db, after['storage_type_id']
            )
        await log_action_async(
            db,
            organization_id=_org_id(user),
            user_id=user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.STORAGE,
            target_id=storage.id,
            snapshot={
                'name': storage.name,
                'before': before_values,
                'after': after_values,
            },
        )

    if parent_changed and relocation == 'physical':
        await db.flush()
        await record_moved_location_async(
            db,
            organization_id=_org_id(user),
            user_id=user.id,
            location=storage,
            from_parent_id=before['parent_id'],
        )

    await event_bus.emit_transactional(
        db,
        SystemEvent.STORAGE_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'location_id': str(storage.id),
                'changes': update_data,
            }
        ),
    )
    await db.flush()
    await db.refresh(storage)
    await interceptor_pipeline.run_after_storage_update(
        storage.id, update_data, context
    )
    return storage


async def archive_storage(
    db: AsyncSession,
    storage: StorageLocation,
    data: StorageArchiveRequest,
    user: UserContextDTO,
) -> StorageLocation:
    """Archive a location, optionally relocating its items first.

    The flag lives in the existing JSONB ``settings`` (decision: no new Core
    column). Items in the location and all of its descendants are moved to
    *move_items_to* when given; without a target, a location that still
    holds items is rejected.
    """
    from app.core.public_api import core_api
    from app.models.item import Item
    from app.services.storage._queries import (
        descendant_ids_async,
        get_storage_async,
    )

    if user.organization_id is None:
        raise ServiceRejectionError('organization_required')
    org_id: UUID = user.organization_id
    descendant_ids = await descendant_ids_async(db, org_id, storage.id)
    target = None
    if data.move_items_to is not None:
        if data.move_items_to == storage.id:
            raise ServiceRejectionError('storage_archive_target_is_self')
        if data.move_items_to in descendant_ids:
            raise ServiceRejectionError('storage_archive_target_is_descendant')
        target = await get_storage_async(db, org_id, data.move_items_to)
        if target is None:
            raise NotFoundException('storage')
        if (target.settings or {}).get('archived') is True:
            raise ServiceRejectionError('storage_archive_target_archived')

    scope_ids = [storage.id] + descendant_ids
    item_ids = list(
        (
            await db.scalars(
                select(Item.id).where(
                    Item.organization_id == org_id,
                    Item.storage_location_id.in_(scope_ids),
                    Item.is_deleted.is_(False),
                )
            )
        ).all()
    )
    if item_ids and target is None:
        raise ServiceRejectionError(
            'storage_archive_blocked_by_items', count=len(item_ids)
        )
    for item_id in item_ids:
        assert target is not None  # guaranteed: items exist ⇒ target required
        await core_api.items.transfer_async(
            db,
            org_id,
            item_id,
            target.id,
            user_id=user.id,
        )

    settings = dict(storage.settings or {})
    settings['archived'] = True
    storage.settings = settings
    flag_modified(storage, 'settings')
    await log_action_async(
        db,
        organization_id=_org_id(user),
        user_id=user.id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.STORAGE,
        target_id=storage.id,
        snapshot={
            'name': storage.name,
            'before': {'archived': False},
            'after': {'archived': True},
        },
        reason='ARCHIVED',
    )
    await db.flush()
    await db.refresh(storage)
    return storage


async def unarchive_storage(
    db: AsyncSession,
    storage: StorageLocation,
    user: UserContextDTO,
) -> StorageLocation:
    """Put an archived location back on the lists, trees and pickers.

    Archiving is where a location that may not be deleted is sent, so the
    door has to open both ways — the only way back used to be an UPDATE
    against the database. Restoring under a still-archived parent is
    refused: the child would return to a branch that is not there.
    """
    from app.services.storage._queries import get_storage_async

    if user.organization_id is None:
        raise ServiceRejectionError('organization_required')
    if storage.parent_id is not None:
        parent = await get_storage_async(db, user.organization_id, storage.parent_id)
        if parent is not None and (parent.settings or {}).get('archived') is True:
            raise ServiceRejectionError('storage_restore_parent_archived')

    settings = dict(storage.settings or {})
    was_archived = settings.pop('archived', None) is True
    storage.settings = settings
    flag_modified(storage, 'settings')
    if was_archived:
        await log_action_async(
            db,
            organization_id=_org_id(user),
            user_id=user.id,
            action=AuditAction.RESTORE,
            target_type=AuditTargetType.STORAGE,
            target_id=storage.id,
            snapshot={
                'name': storage.name,
                'before': {'archived': True},
                'after': {'archived': False},
            },
            reason='RESTORED',
        )
    await db.flush()
    await db.refresh(storage)
    return storage


async def delete_storage(
    db: AsyncSession, storage: StorageLocation, user: UserContextDTO
) -> None:
    """Delete storage location after running interceptors."""
    # Server-side guard: prevent deleting storage with items
    from sqlalchemy import func

    from app.models.item import Item
    from app.models.stock_move import StockMove

    # Serialize DELETE with any concurrent stock_move INSERT for the same
    # storage. Prevents TOCTOU where move_count check passes (no moves yet),
    # but a concurrent item change inserts a StockMove between check and
    # the DELETE, triggering the ck_stock_moves_at_least_one_location
    # violation via the FK ON DELETE SET NULL cascade.
    await acquire_advisory_lock(db, f'storage_delete:{storage.id}')

    item_count = await db.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.storage_location_id == storage.id, Item.is_deleted.is_(False))
    )
    if item_count and item_count > 0:
        raise ServiceRejectionError('storage_delete_failed_items')

    # Server-side guard: prevent deleting storage referenced by StockMove ledger.
    # The FK on from_location_id / to_location_id uses ON DELETE SET NULL,
    # which would nullify the column — but the ck_stock_moves_at_least_one_location
    # CHECK constraint forbids both columns from being NULL simultaneously,
    # so the cascading UPDATE fails. Reject deletion and require an explicit
    # archival workflow before removing storages that participate in history.
    move_count = await db.scalar(
        select(func.count())
        .select_from(StockMove)
        .where(
            (StockMove.from_location_id == storage.id)
            | (StockMove.to_location_id == storage.id)
        )
    )
    if move_count and move_count > 0:
        raise ServiceRejectionError(
            'storage_delete_blocked_by_movements', count=move_count
        )

    # And the stock the register holds here. A live record on the location,
    # or a reservation row promising its stock, with no movement naming the
    # location would leave the register with the location, and no movement
    # would say so.
    if await locations_holding_stock_async(db, _org_id(user), [storage.id]):
        raise ServiceRejectionError('storage_delete_blocked_by_stock')

    # Defense-in-depth: if a StockMove was concurrently inserted after our
    # move_count check (despite the advisory lock, e.g. lock not held by
    # the inserter), the FK SET NULL cascade may now violate the CHECK.
    # Translate the IntegrityError into a retryable business-rule error
    # instead of a 500. Modules must guard their own references via
    # storage interceptors (run below, before any DELETE is attempted);
    # any other constraint that still fires here gets a generic message
    # naming it instead of a misleading stock-movement one.
    from sqlalchemy.exc import IntegrityError

    context = build_module_context(db, user.organization_id, user)
    await interceptor_pipeline.run_before_storage_delete(storage.id, context)

    # Written before the delete: the row the entry names is about to stop
    # existing, and the journal is the only place its name survives.
    await log_action_async(
        db,
        organization_id=_org_id(user),
        user_id=user.id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.STORAGE,
        target_id=storage.id,
        snapshot={
            'name': storage.name,
            'parent_id': audit_value(storage.parent_id),
            'parent_name': await _parent_name(db, _org_id(user), storage.parent_id),
            'usage': audit_value(storage.usage),
        },
    )

    # The children are LIFTED, not orphaned: every confirmation in the
    # application promises that the child locations move up a level, and the
    # FK's ON DELETE SET NULL would otherwise send them all to the top of the
    # tree — a rebuild nobody was told about. Reparenting first also leaves
    # the cascade nothing to fire on. Grandchildren are not touched: they keep
    # their own parent, which is the child that just moved.
    #
    # The lifted children land on the level the doomed row still stands on, so
    # a child bearing the deleted row's own name would meet it in the sibling-
    # name index — for a state the delete does not leave behind (one place of
    # that name on the level). The doomed row therefore gives up its name
    # first; the audit entry above already holds it. A child that meets a
    # different, surviving sibling still collides, and that refusal is right.
    try:
        await db.execute(
            update(StorageLocation)
            .where(StorageLocation.id == storage.id)
            .values(name=str(storage.id))
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            update(StorageLocation)
            .where(
                StorageLocation.organization_id == _org_id(user),
                StorageLocation.parent_id == storage.id,
            )
            .values(parent_id=storage.parent_id)
        )
        await db.delete(storage)
        await db.flush()
    except IntegrityError as exc:
        # No rollback here: the transaction belongs to the caller, and a
        # rollback would silently erase everything the caller wrote before
        # asking for this delete — journal entries included. The failed
        # flush has poisoned this transaction for further SQL, so the
        # caller ends it; the request-scoped session rolls back on teardown.
        constraint = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
        if constraint == 'ck_stock_moves_at_least_one_location':
            raise ServiceRejectionError(
                'storage_delete_concurrent_movements', error=exc.orig
            ) from exc
        raise ServiceRejectionError(
            'storage_delete_blocked_by_references', constraint=constraint
        ) from exc

    # One delete is the delete: the flush above already sent it, and a
    # second call on a flushed-and-deleted instance only confuses the
    # unit of work. The commit is the caller's: the request-scoped session
    # commits once, on success, and a service that commits mid-flight
    # slices the caller's unit of work in two.
    storage_id = storage.id
    await event_bus.emit_transactional(
        db,
        SystemEvent.STORAGE_DELETED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'location_id': str(storage_id),
            }
        ),
    )
    await interceptor_pipeline.run_after_storage_delete(storage_id, context)
