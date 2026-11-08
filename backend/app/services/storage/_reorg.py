"""Transactional batch reorganization of the storage location tree.

The reorg modal used to save its changes as a sequence of individual
create/update/delete requests — a failure in the middle left the tree
half-applied. This service executes the whole operation list inside one
transaction and validates the FINAL tree state, so an intermediate cycle
that disappears by the end of the batch (e.g. swapping two nodes) is legal
while a batch ending in a cycle changes nothing and reports the reason.

Rejection contract: any structural or business violation rejects the whole
batch — nothing is applied, ``applied=False`` and the rejections carry the
operation index and a reason.

A move says what it means (``relocation``): a layout correction writes the
journal row and nothing else, a physical move also records what moved with
the location (``_relocation``). A dry run validates the batch the same way
and answers, per move, what it would carry — the scope the confirmation
names before the person moving chooses.
"""

from uuid import UUID, uuid4

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import ServiceRejectionError
from app.core.interceptors import interceptor_pipeline
from app.i18n.service import get_current_lang, get_error_message
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.stock_move import StockMove
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.storage_location import (
    StorageMoveScope,
    StorageReorgOperation,
    StorageReorgRejection,
    StorageReorgRequest,
    StorageReorgResponse,
)
from app.services.audit_service import audit_value, log_action_async
from app.services.storage._codes import code_for_new_location_async
from app.services.storage._queries import locations_holding_stock_async
from app.services.storage._relocation import (
    path_to,
    products_in_async,
    record_relocation_async,
    subtree_of,
    top_of,
)


class _Plan:
    """Resolved batch: candidate final state plus the planned operations."""

    def __init__(self, name_by_id: dict, parent_by_id: dict, usage_by_id: dict) -> None:
        self.name_by_id = dict(name_by_id)
        self.parent_map = dict(parent_by_id)
        # Kept apart from ``parent_map``, which resolution mutates into the
        # candidate final tree: the journal needs the parent each node left,
        # as it read before the batch.
        self.original_parent_by_id = dict(parent_by_id)
        self.usage_by_id = dict(usage_by_id)
        self.deleted_ids: list[UUID] = []
        self.creates: list[tuple[str, dict]] = []  # (temporary_id, data)
        self.moves: list[tuple[UUID, UUID | None]] = []
        # Beside ``moves``, one per move: the operation's index and what the
        # move means (``StorageReorgOperation.relocation``).
        self.move_ops: list[tuple[int, str | None]] = []
        self.temp_to_id: dict[str, UUID] = {}
        self.rejections: list[StorageReorgRejection] = []

    @property
    def rejected(self) -> bool:
        return bool(self.rejections)


def _find_cycle(
    parent_map: dict[UUID, UUID | None], excluded: set[UUID] | None = None
) -> list[UUID] | None:
    """Return the ids on a cycle in *parent_map*, or None when it is a forest.

    Walks the parent chain from every node; a revisited node means the walk
    entered a loop. Nodes in *excluded* (deleted in the batch) are skipped as
    starts and break the walk — their chains are irrelevant after the batch,
    so deleting a whole cyclic pair is legal. Runs on the final map only —
    intermediate states of a batch are irrelevant by design.
    """
    excluded = excluded or set()
    for start in parent_map:
        if start in excluded:
            continue
        chain: list[UUID] = []
        seen: set[UUID] = set()
        current: UUID | None = start
        while current is not None:
            if current in seen:
                return chain[chain.index(current) :]
            seen.add(current)
            chain.append(current)
            current = parent_map.get(current)
            if current in excluded:
                break
    return None


async def _load_snapshot(db: AsyncSession, org_id: UUID) -> tuple[dict, dict, dict]:
    """Return (name_by_id, parent_by_id, usage_by_id) for the org's locations.

    The usage and the names ride along for the journal: a delete entry names
    what the location held and where it sat, and the row is gone by the time
    the entry is written.
    """
    rows = (
        await db.execute(
            select(
                StorageLocation.id,
                StorageLocation.name,
                StorageLocation.parent_id,
                StorageLocation.usage,
            ).where(StorageLocation.organization_id == org_id)
        )
    ).all()
    name_by_id = {row[0]: row[1] for row in rows}
    parent_by_id = {row[0]: row[2] for row in rows}
    usage_by_id = {row[0]: row[3] for row in rows}
    return name_by_id, parent_by_id, usage_by_id


def _reject(plan: _Plan, index: int, op: StorageReorgOperation, reason: str) -> None:
    plan.rejections.append(
        StorageReorgRejection(
            index=index, op=op.op, temporary_id=op.temporary_id, reason=reason
        )
    )


def _resolve_parent(
    plan: _Plan, raw: str | None, index: int, op: StorageReorgOperation
) -> tuple[UUID | None, bool]:
    """Resolve a parent reference (UUID, temporary key or None)."""
    if raw is None:
        return None, True
    parsed: UUID | None = None
    try:
        parsed = UUID(raw)
    except (ValueError, TypeError, AttributeError):
        parsed = None
    if parsed is not None:
        if parsed in plan.parent_map and parsed not in plan.deleted_ids:
            return parsed, True
        _reject(plan, index, op, 'Parent location does not exist in this organization.')
        return None, False
    if raw in plan.temp_to_id:
        return plan.temp_to_id[raw], True
    _reject(
        plan,
        index,
        op,
        f'Unknown temporary id "{raw}": it must be created earlier in the same batch.',
    )
    return None, False


def _resolve_delete(plan: _Plan, index: int, op: StorageReorgOperation) -> None:
    if op.id is None or op.id not in plan.parent_map:
        _reject(plan, index, op, 'Location does not exist in this organization.')
        return
    if op.id in plan.deleted_ids:
        _reject(plan, index, op, 'Location is deleted twice in this batch.')
        return
    plan.deleted_ids.append(op.id)


def _resolve_create(plan: _Plan, index: int, op: StorageReorgOperation) -> None:
    if not op.temporary_id:
        _reject(plan, index, op, 'temporary_id is required for create.')
        return
    if op.temporary_id in plan.temp_to_id:
        _reject(plan, index, op, 'temporary_id must be unique within the batch.')
        return
    if not op.name or not op.name.strip():
        _reject(plan, index, op, 'Name is required for create.')
        return
    parent, ok = _resolve_parent(plan, op.parent_id, index, op)
    if not ok:
        return
    new_id = uuid4()
    plan.temp_to_id[op.temporary_id] = new_id
    plan.creates.append(
        (
            op.temporary_id,
            {
                'id': new_id,
                'name': op.name.strip(),
                'parent_id': parent,
                # A person reorganizing their shelves creates shelves.
                'usage': LocationUsage.INTERNAL.value,
            },
        )
    )
    plan.parent_map[new_id] = parent
    plan.name_by_id[new_id] = op.name.strip()


def _resolve_move(plan: _Plan, index: int, op: StorageReorgOperation) -> None:
    if op.id is None or op.id not in plan.parent_map or op.id in plan.deleted_ids:
        _reject(plan, index, op, 'Location does not exist in this organization.')
        return
    parent, ok = _resolve_parent(plan, op.parent_id, index, op)
    if not ok:
        return
    if parent == op.id:
        _reject(plan, index, op, 'A location cannot be its own parent.')
        return
    plan.moves.append((op.id, parent))
    plan.move_ops.append((index, op.relocation))
    plan.parent_map[op.id] = parent


def _resolve_operations(plan: _Plan, data: StorageReorgRequest) -> None:
    """Translate the operation list into the candidate final map."""
    handlers = {
        'delete': _resolve_delete,
        'create': _resolve_create,
        'move': _resolve_move,
    }
    for index, op in enumerate(data.operations):
        handler = handlers.get(op.op)
        if handler is None:
            _reject(plan, index, op, f'Unknown operation "{op.op}".')
            continue
        handler(plan, index, op)


def _validate_final_state(plan: _Plan, data: StorageReorgRequest) -> None:
    """Check dangling parents, cycles and sibling-name uniqueness."""
    deleted_set = set(plan.deleted_ids)
    for node_id, parent_id in plan.parent_map.items():
        if node_id in deleted_set:
            continue  # the node itself is deleted — nothing is orphaned
        if parent_id in deleted_set:
            delete_index = _index_of(data, 'delete', id=parent_id)
            op = data.operations[delete_index]
            _reject(
                plan,
                delete_index,
                op,
                'Deleting this location would orphan its children; '
                'delete or move them in the same batch first.',
            )
    cycle = _find_cycle(plan.parent_map, deleted_set)
    if cycle:
        cycle_set = set(cycle)
        blame = _max_touching_index(data, cycle_set, plan.temp_to_id)
        _reject(
            plan,
            blame,
            data.operations[blame],
            'This operation would create a cycle in the location hierarchy.',
        )
    created_ids = {plan.temp_to_id[t] for t, _ in plan.creates}
    # Who holds a name on a level in the final tree: every surviving node, so
    # a twin is found whichever of the two the snapshot happens to list first.
    holders: dict[tuple[UUID | None, str], set[UUID]] = {}
    for node, name in plan.name_by_id.items():
        if node not in created_ids and node not in deleted_set:
            holders.setdefault((plan.parent_map.get(node), name), set()).add(node)
    for temp_id, create_data in plan.creates:
        key = (create_data.get('parent_id'), create_data['name'])
        if key in holders:
            create_index = _index_of(data, 'create', temporary_id=temp_id)
            _reject(
                plan,
                create_index,
                data.operations[create_index],
                _name_taken_reason(create_data['name']),
            )
        holders.setdefault(key, set()).add(plan.temp_to_id[temp_id])
    # A move lands among the siblings of its new parent: a place of the same
    # name already there — one that stays, or another one moving in — is the
    # same refusal a create gets, said before the write instead of as the
    # index's violation after it.
    for move_id, new_parent in plan.moves:
        name = plan.name_by_id.get(move_id, '')
        if holders.get((new_parent, name), set()) - {move_id}:
            move_index = _index_of(data, 'move', id=move_id)
            _reject(
                plan,
                move_index,
                data.operations[move_index],
                _name_taken_reason(name),
            )


def _name_taken_reason(name: str) -> str:
    """The refusal for a name already used on the level, in the reader's language."""
    return get_error_message('storage_name_collision', get_current_lang(), name=name)


def _index_of(
    data: StorageReorgRequest,
    op_name: str,
    *,
    id: UUID | None = None,
    temporary_id: str | None = None,
) -> int:
    for index, op in enumerate(data.operations):
        if op.op != op_name:
            continue
        if id is not None and op.id == id:
            return index
        if temporary_id is not None and op.temporary_id == temporary_id:
            return index
    return 0


def _max_touching_index(
    data: StorageReorgRequest,
    cycle_set: set[UUID],
    temp_to_id: dict[str, UUID],
) -> int:
    """Index of the last operation that assigned a parent to a cycle member."""
    blame = 0
    for index, op in enumerate(data.operations):
        if op.op == 'move' and op.id is not None and op.id in cycle_set:
            blame = index
        elif (
            op.op == 'create'
            and op.temporary_id is not None
            and temp_to_id.get(op.temporary_id) in cycle_set
        ):
            blame = index
    return blame


async def _check_delete_guards(
    db: AsyncSession, org_id: UUID, plan: _Plan, data: StorageReorgRequest
) -> None:
    """Reject deletes of locations that hold items or ledger references."""
    if not plan.deleted_ids:
        return
    item_rows = (
        await db.execute(
            select(Item.storage_location_id, func.count())
            .where(
                Item.organization_id == org_id,
                Item.storage_location_id.in_(plan.deleted_ids),
                Item.is_deleted.is_(False),
            )
            .group_by(Item.storage_location_id)
        )
    ).all()
    item_counts: dict[UUID, int] = {row[0]: row[1] for row in item_rows}
    from_rows = (
        await db.execute(
            select(StockMove.from_location_id, func.count())
            .where(StockMove.from_location_id.in_(plan.deleted_ids))
            .group_by(StockMove.from_location_id)
        )
    ).all()
    from_counts: dict[UUID | None, int] = {row[0]: row[1] for row in from_rows}
    to_rows = (
        await db.execute(
            select(StockMove.to_location_id, func.count())
            .where(StockMove.to_location_id.in_(plan.deleted_ids))
            .group_by(StockMove.to_location_id)
        )
    ).all()
    to_counts: dict[UUID | None, int] = {row[0]: row[1] for row in to_rows}
    holding_stock = await locations_holding_stock_async(
        db, org_id, list(plan.deleted_ids)
    )
    for delete_id in plan.deleted_ids:
        delete_index = _index_of(data, 'delete', id=delete_id)
        op = data.operations[delete_index]
        item_total = item_counts.get(delete_id, 0)
        if item_total:
            _reject(
                plan,
                delete_index,
                op,
                get_error_message('storage_delete_failed_items', get_current_lang()),
            )
        move_total = from_counts.get(delete_id, 0) + to_counts.get(delete_id, 0)
        if move_total:
            _reject(
                plan,
                delete_index,
                op,
                get_error_message(
                    'storage_delete_blocked_by_movements',
                    get_current_lang(),
                    count=move_total,
                ),
            )
        if delete_id in holding_stock:
            _reject(
                plan,
                delete_index,
                op,
                get_error_message(
                    'storage_delete_blocked_by_stock', get_current_lang()
                ),
            )


async def _run_before_hooks(
    db: AsyncSession, user: UserContextDTO, org_id: UUID, plan: _Plan
) -> StorageReorgResponse | None:
    """Run interceptor before-hooks; return a rejection response on error."""
    context = build_module_context(db, org_id, user)
    try:
        for temp_id, create_data in plan.creates:
            mutated = await interceptor_pipeline.run_before_storage_create(
                create_data, context
            )
            if mutated.get('parent_id') is not None:
                plan.parent_map[plan.temp_to_id[temp_id]] = mutated['parent_id']
        for delete_id in plan.deleted_ids:
            await interceptor_pipeline.run_before_storage_delete(delete_id, context)
        for move_id, new_parent in plan.moves:
            mutated = await interceptor_pipeline.run_before_storage_update(
                move_id, {'parent_id': new_parent}, context
            )
            if mutated.get('parent_id') is not None:
                plan.parent_map[move_id] = mutated['parent_id']
    except Exception as exc:  # noqa: BLE001 - batch boundary; report, don't crash
        return StorageReorgResponse(
            applied=False,
            rejections=[
                StorageReorgRejection(
                    index=0,
                    op='batch',
                    reason=f'Interceptor rejected the batch: {exc}',
                )
            ],
        )
    return None


def _plan_parent_name(plan: _Plan, parent_id: UUID | None) -> str | None:
    """The parent's name as the plan read it, for the journal.

    Read from the plan, not the database: a parent created by the same batch
    has no row to read, and one deleted by it has no row any more — and the
    journal records what the record was called when the change was made
    (docs/subsystems/AUDIT.md).
    """
    if parent_id is None:
        return None
    return plan.name_by_id.get(parent_id)


async def _log_batch(
    db: AsyncSession, user: UserContextDTO, org_id: UUID, plan: _Plan
) -> None:
    """One journal row per operation, in the shape of the single-door writes.

    The batch used to be the one storage write path that left no trail: a
    person could move a shelf, create a rack and delete a zone in one save,
    and ``/settings/audit-log`` showed none of it. The rows here answer with
    the same shape the edit sheet, the create form and the delete button
    write — the parent named beside its id — and ``meta_data.bulk`` says the
    rows arrived as one batch, as the bulk item edit already does
    (docs/subsystems/AUDIT.md). Written inside the batch's transaction: a
    rejected batch changed nothing, so it journals nothing.
    """
    for delete_id in plan.deleted_ids:
        parent_id = plan.original_parent_by_id.get(delete_id)
        await log_action_async(
            db,
            organization_id=org_id,
            user_id=user.id,
            action=AuditAction.HARD_DELETE,
            target_type=AuditTargetType.STORAGE,
            target_id=delete_id,
            snapshot={
                'name': plan.name_by_id.get(delete_id),
                'parent_id': audit_value(parent_id),
                'parent_name': _plan_parent_name(plan, parent_id),
                'usage': audit_value(plan.usage_by_id.get(delete_id)),
            },
            meta_data={'bulk': True},
        )
    for _temp_id, create_data in plan.creates:
        parent_id = create_data.get('parent_id')
        await log_action_async(
            db,
            organization_id=org_id,
            user_id=user.id,
            action=AuditAction.CREATE,
            target_type=AuditTargetType.STORAGE,
            target_id=create_data['id'],
            snapshot={
                'name': create_data['name'],
                'parent_id': audit_value(parent_id),
                'parent_name': _plan_parent_name(plan, parent_id),
                'usage': audit_value(create_data.get('usage')),
            },
            meta_data={'bulk': True},
        )
    # The parent a move left, tracked as the batch applies its moves in
    # order: two moves of one node journal the same pair of changes the two
    # single edits would have. A re-filing that changed nothing is not an
    # event — the same rule the edit sheet applies.
    moved_from: dict[UUID, UUID | None] = {}
    for move_id, new_parent in plan.moves:
        before_parent = moved_from.get(move_id, plan.original_parent_by_id.get(move_id))
        if before_parent == new_parent:
            continue
        moved_from[move_id] = new_parent
        await log_action_async(
            db,
            organization_id=org_id,
            user_id=user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.STORAGE,
            target_id=move_id,
            snapshot={
                'name': plan.name_by_id.get(move_id),
                'before': {
                    'parent_id': audit_value(before_parent),
                    'parent_name': _plan_parent_name(plan, before_parent),
                },
                'after': {
                    'parent_id': audit_value(new_parent),
                    'parent_name': _plan_parent_name(plan, new_parent),
                },
            },
            meta_data={'bulk': True},
        )


async def _apply_writes(
    db: AsyncSession, user: UserContextDTO, org_id: UUID, plan: _Plan
) -> tuple[dict[str, UUID], StorageReorgResponse | None]:
    """Execute deletes, creates and moves as one unit inside a savepoint.

    A refused batch takes only its own writes back; the caller's transaction
    is left as it was and commits once, on success.
    """
    created_ids: dict[str, UUID] = {}
    try:
        async with db.begin_nested():
            # One address rule across all write paths: a location filed under a
            # module's location carries the module's tag unless it brings its own.
            # The batch resolves parents by id, so their tags are fetched once,
            # here, rather than re-asking per row.
            batch_parent_ids = {
                parent
                for parent in [
                    *(data.get('parent_id') for _, data in plan.creates),
                    *(new_parent for _, new_parent in plan.moves),
                ]
                if parent is not None
            }
            tag_by_parent: dict = {}
            if batch_parent_ids:
                parent_rows = await db.scalars(
                    select(StorageLocation).where(
                        StorageLocation.id.in_(batch_parent_ids)
                    )
                )
                tag_by_parent = {
                    row.id: row.context_tag for row in parent_rows if row.context_tag
                }
            # The index refuses a state the batch only passes through (a place
            # deleted while its namesake child moves up, two namesakes swapping
            # parents), though the final tree it validated is fine. Every mover
            # therefore stands under its own id as a name while the tree is
            # rearranged, and takes its name back once it is.
            movers = list(dict.fromkeys(move_id for move_id, _ in plan.moves))
            if movers:
                await db.execute(
                    update(StorageLocation)
                    .where(
                        StorageLocation.organization_id == org_id,
                        StorageLocation.id.in_(movers),
                    )
                    .values(name=cast(StorageLocation.id, String))
                    .execution_options(synchronize_session=False)
                )
            for delete_id in plan.deleted_ids:
                row = await db.get(StorageLocation, delete_id)
                if row is None:
                    raise ServiceRejectionError(
                        'storage_vanished_during_batch', location=delete_id
                    )
                await db.delete(row)
            # Sent now, not with the creates: the unit of work writes inserts
            # before deletes, and a place created under a deleted namesake's
            # name would meet it.
            await db.flush()
            for temp_id, create_data in plan.creates:
                model_columns = StorageLocation.__table__.columns.keys()
                final_data = {
                    k: v for k, v in create_data.items() if k in model_columns
                }
                if not final_data.get('context_tag'):
                    inherited = tag_by_parent.get(final_data.get('parent_id'))
                    if inherited:
                        final_data['context_tag'] = inherited
                storage = StorageLocation(**final_data)
                storage.organization_id = org_id  # type: ignore[assignment]
                storage.created_by = user.id
                # The same rule as a single create: the next shelf code under a
                # numbered parent — one created earlier in this batch included,
                # it is flushed — and a random code otherwise.
                storage.short_code = await code_for_new_location_async(
                    db, org_id, storage.parent_id
                )
                db.add(storage)
                await db.flush()
                created_ids[temp_id] = storage.id
                # A node created earlier in the same batch can be a move target's
                # parent — its tag participates from here on.
                if storage.context_tag:
                    tag_by_parent[storage.id] = storage.context_tag
            for move_id, new_parent in plan.moves:
                row = await db.get(StorageLocation, move_id)
                if row is None:
                    raise ServiceRejectionError(
                        'storage_vanished_during_batch', location=move_id
                    )
                row.parent_id = new_parent
                if not row.context_tag:
                    inherited = tag_by_parent.get(new_parent)
                    if inherited:
                        row.context_tag = inherited
            await db.flush()
            for move_id in movers:
                await db.execute(
                    update(StorageLocation)
                    .where(
                        StorageLocation.organization_id == org_id,
                        StorageLocation.id == move_id,
                    )
                    .values(name=plan.name_by_id[move_id])
                    .execution_options(synchronize_session=False)
                )
            await _record_relocations(db, user, org_id, plan)
            await _log_batch(db, user, org_id, plan)
            await _emit_events(db, org_id, plan, created_ids)
    except Exception as exc:  # noqa: BLE001 - roll back the whole batch
        return {}, StorageReorgResponse(
            applied=False,
            rejections=[
                StorageReorgRejection(
                    index=0, op='batch', reason=f'Batch failed: {exc}'
                )
            ],
        )
    return created_ids, None


async def _move_scopes(
    db: AsyncSession, org_id: UUID, plan: _Plan
) -> list[StorageMoveScope]:
    """What each move of the batch carries, read on the batch's final tree."""
    deleted = set(plan.deleted_ids)
    scopes: list[StorageMoveScope] = []
    for (move_id, _new_parent), (index, _kind) in zip(
        plan.moves, plan.move_ops, strict=True
    ):
        subtree = subtree_of(plan.parent_map, move_id, deleted)
        from_parent = plan.original_parent_by_id.get(move_id)
        to_parent = plan.parent_map.get(move_id)
        scopes.append(
            StorageMoveScope(
                index=index,
                id=move_id,
                name=plan.name_by_id.get(move_id, ''),
                locations_inside=len(subtree) - 1,
                products=await products_in_async(db, org_id, subtree),
                from_path=path_to(
                    plan.name_by_id, plan.original_parent_by_id, from_parent
                ),
                to_path=path_to(plan.name_by_id, plan.parent_map, to_parent),
                warehouse_changes=top_of(plan.original_parent_by_id, move_id)
                != top_of(plan.parent_map, move_id),
            )
        )
    return scopes


async def _record_relocations(
    db: AsyncSession, user: UserContextDTO, org_id: UUID, plan: _Plan
) -> None:
    """A document and its movements for every move that physically happened.

    Read on the final tree, once the moves are written: the products that
    moved are the ones standing in the location and below it at the end of
    the batch, and a move that ends under the parent it started from moved
    nothing.
    """
    deleted = set(plan.deleted_ids)
    # A node moved twice in one batch moved once, from where it stood to
    # where it ends; its last operation says what that move meant.
    kind_by_move = {
        move_id: kind
        for (move_id, _parent), (_index, kind) in zip(
            plan.moves, plan.move_ops, strict=True
        )
    }
    for move_id, kind in kind_by_move.items():
        if kind != 'physical':
            continue
        from_parent = plan.original_parent_by_id.get(move_id)
        to_parent = plan.parent_map.get(move_id)
        if from_parent == to_parent:
            continue
        await record_relocation_async(
            db,
            organization_id=org_id,
            user_id=user.id,
            location_id=move_id,
            location_name=plan.name_by_id.get(move_id, ''),
            from_parent_id=from_parent,
            to_parent_id=to_parent,
            from_path=path_to(plan.name_by_id, plan.original_parent_by_id, from_parent),
            to_path=path_to(plan.name_by_id, plan.parent_map, to_parent),
            location_ids=subtree_of(plan.parent_map, move_id, deleted),
        )


async def _emit_events(
    db: AsyncSession, org_id: UUID, plan: _Plan, created_ids: dict[str, UUID]
) -> None:
    """Write the batch's events to the outbox, in the batch's transaction."""
    for temp_id, _ in plan.creates:
        await event_bus.emit_transactional(
            db,
            SystemEvent.STORAGE_CREATED,
            TenantEventPayload.model_validate(
                {
                    'organization_id': str(org_id),
                    'location_id': str(created_ids[temp_id]),
                }
            ),
        )
    for delete_id in plan.deleted_ids:
        await event_bus.emit_transactional(
            db,
            SystemEvent.STORAGE_DELETED,
            TenantEventPayload.model_validate(
                {'organization_id': str(org_id), 'location_id': str(delete_id)}
            ),
        )
    for move_id, new_parent in plan.moves:
        await event_bus.emit_transactional(
            db,
            SystemEvent.STORAGE_UPDATED,
            TenantEventPayload.model_validate(
                {
                    'organization_id': str(org_id),
                    'location_id': str(move_id),
                    'changes': {'parent_id': new_parent},
                }
            ),
        )


async def _run_after_hooks(
    db: AsyncSession,
    user: UserContextDTO,
    org_id: UUID,
    plan: _Plan,
    created_ids: dict[str, UUID],
) -> None:
    """Run the after-hooks once the batch is committed — parity with the
    single-op paths."""
    context = build_module_context(db, org_id, user)
    for temp_id, create_data in plan.creates:
        await interceptor_pipeline.run_after_storage_create(
            created_ids[temp_id], create_data, context
        )
    for delete_id in plan.deleted_ids:
        await interceptor_pipeline.run_after_storage_delete(delete_id, context)
    for move_id, new_parent in plan.moves:
        await interceptor_pipeline.run_after_storage_update(
            move_id, {'parent_id': new_parent}, context
        )


async def execute_storage_reorg(
    db: AsyncSession,
    data: StorageReorgRequest,
    user: UserContextDTO,
) -> StorageReorgResponse:
    """Execute the operation list atomically or reject it as a whole."""
    if user.organization_id is None:
        raise ServiceRejectionError('organization_required')
    org_id: UUID = user.organization_id
    name_by_id, parent_by_id, usage_by_id = await _load_snapshot(db, org_id)
    plan = _Plan(name_by_id, parent_by_id, usage_by_id)

    _resolve_operations(plan, data)
    if plan.rejected:
        return StorageReorgResponse(applied=False, rejections=plan.rejections)

    # A dry run writes nothing, so it asks no module to approve a write.
    if not data.dry_run:
        hook_error = await _run_before_hooks(db, user, org_id, plan)
        if hook_error is not None:
            return hook_error

    _validate_final_state(plan, data)
    if plan.rejected:
        return StorageReorgResponse(applied=False, rejections=plan.rejections)

    await _check_delete_guards(db, org_id, plan, data)
    if plan.rejected:
        return StorageReorgResponse(applied=False, rejections=plan.rejections)

    if data.dry_run:
        return StorageReorgResponse(
            applied=False, moves=await _move_scopes(db, org_id, plan)
        )

    created_ids, write_error = await _apply_writes(db, user, org_id, plan)
    if write_error is not None:
        return write_error

    await _run_after_hooks(db, user, org_id, plan, created_ids)
    return StorageReorgResponse(applied=True, created=created_ids)
