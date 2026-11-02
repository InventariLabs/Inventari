# module_writes: StockTake, StockTakeItem
"""
Business logic for stock take operations.

Core domain logic (create, summary, report, finalize) lives here; CRUD and
query helpers used by router handlers live in _stock_take_crud.py and are
re-exported below for backward compatibility.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, overload
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    CountDifferenceDTO,
    ItemDTO,
    StorageDTO,
    UserContextDTO,
)
from app.core.db_utils import acquire_advisory_lock, get_org_owned_or_404_async
from app.core.deps import require_org
from app.core.exceptions import (
    ConflictException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.modules.warehouse.warehouse_api import warehouse_api

# Re-export CRUD/query helpers so existing callers (router) are unaffected.
from ._stock_take_crud import (  # noqa: F401
    add_surplus_item,
    apply_item_count,
    bulk_count_items_and_commit,
    close_location,
    count_item_and_commit,
    delete_stock_take_entity,
    get_stock_take_item_or_404,
    get_stock_take_items_filtered,
    get_stock_take_items_simple,
    list_closed_locations,
    list_stock_takes_filtered,
    update_stock_take_fields,
    update_stock_take_status_service,
)
from .models import StockTake, StockTakeItem, StockTakeStatus
from .schemas import (
    StockTakeComplete,
    StockTakeItemWithDetails,
    StockTakeReport,
)
from .storage_lookup_service import get_storage_tree

# A single stock-take row may not raise an item's quantity beyond this
# multiple of its system_quantity without someone saying so. The cap is a
# tolerance threshold, not an edit: a count above it holds the whole posting
# back (409) until the supervisor accepts it with force_over_cap=True, which
# then writes the counted number as counted. Rewriting the count in silence —
# what this used to do — leaves a report confirming a number nobody stored.
_MAX_GROWTH_FACTOR = 5


def _rows_over_tolerance(
    stock_take: StockTake, items: list[StockTakeItem]
) -> list[dict[str, Any]]:
    """Counted rows the stock take's own tolerance says are too far out.

    A tolerance is the organization saying how big a difference has to be
    before it is worth investigating; anything inside it is measurement noise
    and posts itself. Outside it, the standard every warehouse system follows
    is that the posting waits for somebody who may accept it — SAP gives each
    user group a limit and refuses the posting to anyone under it, Dynamics
    blocks the line, and the WMS floor sends it back to be counted again.

    Without a tolerance configured there is no "too far out" to speak of, so
    the count posts as it always has: the rule cannot be stricter than the
    number the organization declined to set.
    """
    if stock_take.tolerance_percent is None:
        return []
    return [
        {
            'item_id': str(item.item_id),
            'item_name': item.item_name,
            'system_quantity': float(item.system_quantity or 0),
            'counted_quantity': float(item.counted_quantity or 0),
            'reason_code': item.discrepancy_reason_code,
        }
        for item in items
        if item.item_id and item.counted_quantity is not None and item.is_discrepancy
    ]


async def _the_shelf_today(
    db: AsyncSession,
    organization_id: UUID,
    stock_take: StockTake,
) -> dict[UUID, ItemDTO]:
    """Every item row standing on the counted shelf right now, by id.

    One read answers both questions the posting asks about the shelf: has a
    counted row's record moved since the snapshot (the staleness guard), and
    what do the records add up to per (template, location) — the total the
    count settles that shelf on.

    The count claims the location and its descendants, so the shelf is the
    tree below it, and the row of an item that has left that tree is simply
    not in here. That is the answer to a third question too: a row whose item
    is no longer standing where it was counted is not the shelf's to settle.
    """
    tree_ids, _family_ids, _paths = await get_storage_tree(
        db, organization_id, stock_take.storage_location_id
    )
    standing: dict[UUID, ItemDTO] = {}
    for location_id in tree_ids:
        for item in await core_api.items.list_async(
            db, organization_id, storage_location_id=location_id, limit=5000
        ):
            standing[item.id] = item
    return standing


async def _rows_whose_stock_moved(
    db: AsyncSession,
    organization_id: UUID,
    stock_take: StockTake,
    items: list[StockTakeItem],
    standing: dict[UUID, ItemDTO],
) -> list[dict[str, Any]]:
    """Counted rows whose system quantity is no longer what the system holds.

    The snapshot is frozen when the count is created and the posting writes an
    absolute quantity, so a movement made in between — a delivery received, a
    picking done, a correction typed — was overwritten without a word.

    The rows are sent back to be counted again, against the quantity that
    stands now: recounting against the frozen number would refuse for ever.
    A delta instead of a refusal is the other way out and the worse one — it
    produces a state nobody observed and can go below zero — so the conflict
    goes to the person who can walk to the shelf.
    """
    moved: list[dict[str, Any]] = []
    for row in items:
        if not row.item_id or row.counted_quantity is None:
            continue
        on_the_shelf = standing.get(row.item_id)
        now = None if on_the_shelf is None else on_the_shelf.quantity
        if now is None:
            # It left the tree since the snapshot. Its quantity is still the
            # thing the posting would overwrite, so it is read where it is.
            moved_away = await core_api.items.get_async(
                db, organization_id, row.item_id
            )
            if moved_away is None:
                continue
            now = moved_away.quantity or Decimal('0')
        if now == (row.system_quantity or Decimal('0')):
            continue
        moved.append(
            {
                'item_id': str(row.item_id),
                'item_name': row.item_name,
                'counted_against': str(row.system_quantity),
                'system_quantity': str(now),
            }
        )
        row.system_quantity = now
        row.recount_requested = True
    return moved


async def _refuse_if_the_stock_moved(
    db: AsyncSession,
    organization_id: UUID,
    stock_take: StockTake,
    items: list[StockTakeItem],
    standing: dict[UUID, ItemDTO],
) -> None:
    """Send stale rows back to be counted again, and say so."""
    moved = await _rows_whose_stock_moved(
        db, organization_id, stock_take, items, standing
    )
    if not moved:
        return
    # The recount marks are the point of the refusal, so they must outlive
    # it. A raise rolls the request back, so the endpoint that surfaces this
    # refusal commits them (``complete_stock_take``). Nothing has been posted
    # at this line: that commit writes the marks and nothing else.
    await db.flush()
    raise ConflictException(
        code='STOCK_TAKE_STOCK_MOVED',
        message=get_error_message(
            'stock_take_stock_moved', get_current_lang(), count=len(moved)
        ),
        details={'moved_items': moved},
    )


async def _release_what_the_shelf_no_longer_covers(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID | None,
    location_id: UUID | None,
    leaving_quantity: Decimal,
) -> None:
    """Give up the holds a counted shelf has no stock behind any more.

    Called with what the shelf is losing, so it is the shelf's holds that
    give way and not one record's: a shelf of ten holding six for a document
    and counted at eight still covers it, and nobody's claim is touched.
    """
    if leaving_quantity <= 0 or template_id is None or location_id is None:
        return
    await core_api.stock.release_unbacked_async(
        db, organization_id, template_id, location_id, leaving_quantity
    )


@dataclass(frozen=True)
class _ShelfPosting:
    """One shelf this count touched: what its records held, and what they hold.

    ``counted_total`` is what the shelf ends up holding — the records of the
    rows standing on it, with every row the count covered replaced by what
    the counter saw. The rows nobody counted keep what their record says,
    which is the snapshot unless something moved it since: a count does not
    wipe stock nobody looked at, and it does not invent stock either.

    ``held_total`` is what the shelf's records held before the count. The
    difference between the two is what the shelf is losing, and it is
    measured against the records because the records are the state: there
    is no other number of the shelf to weigh the count against, and the
    count itself is the authority for this one.

    The movement and the cost layer are written beside the record, by its
    own posting, in the record's own delta. This posting only says what the
    shelf held and what it holds now, for the holds that have to give way
    and for the groups that have to be locked first.
    """

    template_id: UUID
    location_id: UUID
    counted_total: Decimal
    held_total: Decimal

    @property
    def leaving_quantity(self) -> Decimal:
        """What the shelf is losing — what its holds have to give way to."""
        return max(Decimal('0'), self.held_total - self.counted_total)


def _shelf_postings(
    items: list[StockTakeItem],
    standing: dict[UUID, ItemDTO],
) -> list[_ShelfPosting]:
    """What every shelf this count touched held before, and what it holds now.

    A count is the truth about the shelf it covered, so both numbers are
    the records' own: what they added up to before, and what they add up to
    once every row the count covered carries the counter's number. The
    movement ledger is never read here — each counted record carries its own
    delta into it through its own posting, in the same transaction and under the
    group's anchor lock, so a mismatch the ledger was already carrying
    travels with it, neither cured nor widened: the reconciliation pairs are
    there to show it, not the count to hide it.

    The difference between the two numbers is the shelf's loss, and the
    holds that no longer have stock behind it give way to that, before any
    record moves.

    A shelf with no counted row on it is not touched at all: nobody looked
    at it, so there is nothing to say about it.
    """
    held: dict[tuple[UUID, UUID], Decimal] = {}
    for item in standing.values():
        if item.template_id is None or item.location_id is None:
            continue
        key = (item.template_id, item.location_id)
        held[key] = held.get(key, Decimal('0')) + (item.quantity or Decimal('0'))

    counted: dict[tuple[UUID, UUID], Decimal] = dict(held)
    touched: set[tuple[UUID, UUID]] = set()
    for row in items:
        if row.item_id is None or row.counted_quantity is None:
            continue
        where_it_stands = standing.get(row.item_id)
        if (
            where_it_stands is None
            or where_it_stands.template_id is None
            or where_it_stands.location_id is None
        ):
            continue
        key = (where_it_stands.template_id, where_it_stands.location_id)
        here = (
            # A unit counted on another shelf leaves this one whole and
            # stands on that one with what was counted.
            (where_it_stands.template_id, row.storage_location_id)
            if row.expected_location_id is not None
            and row.storage_location_id is not None
            else key
        )
        counted[key] = counted.get(key, Decimal('0')) - (
            where_it_stands.quantity or Decimal('0')
        )
        counted[here] = counted.get(here, Decimal('0')) + Decimal(
            str(row.counted_quantity)
        )
        touched.update((key, here))

    return [
        _ShelfPosting(
            template_id=key[0],
            location_id=key[1],
            counted_total=counted[key],
            held_total=held.get(key, Decimal('0')),
        )
        for key in sorted(touched)
    ]


def _rows_over_cap(items: list[StockTakeItem]) -> list[dict[str, Any]]:
    """Counted rows that would grow an item beyond the tolerance threshold.

    Rows whose system quantity is zero are outside the rule: a first count on
    an empty shelf has no baseline to be a multiple of.
    """
    over_cap: list[dict[str, Any]] = []
    for item in items:
        if not item.item_id or item.counted_quantity is None:
            continue
        if not item.system_quantity:
            continue
        cap = Decimal(str(_MAX_GROWTH_FACTOR)) * Decimal(str(item.system_quantity))
        if Decimal(str(item.counted_quantity)) > cap:
            over_cap.append(
                {
                    'item_id': str(item.item_id),
                    'item_name': item.item_name,
                    'system_quantity': float(item.system_quantity),
                    'counted_quantity': float(item.counted_quantity),
                    'cap': float(cap),
                }
            )
    return over_cap


@overload
async def get_stock_take_or_404(
    stock_take_id: UUID,
    current_user: UserContextDTO,
    db: AsyncSession,
    *,
    with_storage: Literal[False] = False,
) -> StockTake: ...


@overload
async def get_stock_take_or_404(
    stock_take_id: UUID,
    current_user: UserContextDTO,
    db: AsyncSession,
    *,
    with_storage: Literal[True],
) -> tuple[StockTake, StorageDTO | None]: ...


async def get_stock_take_or_404(
    stock_take_id: UUID,
    current_user: UserContextDTO,
    db: AsyncSession,
    *,
    with_storage: bool = False,
) -> StockTake | tuple[StockTake, StorageDTO | None]:
    """Fetch a StockTake belonging to the user's org, or raise 404.

    When ``with_storage=True`` (used by endpoints that render storage or
    storage-type names), returns a ``(StockTake, StorageDTO | None)``
    tuple so callers can read storage data without triggering lazy loads
    on the ORM relationship (which would fail under async sessions).
    """
    lang = get_current_lang()
    stock_take = await get_org_owned_or_404_async(
        db,
        StockTake,
        stock_take_id,
        require_org(current_user),
        resource='stock_take',
        lang=lang,
    )
    if not with_storage:
        return stock_take
    storage_dto = await core_api.locations.get_with_type_async(
        db, require_org(current_user), stock_take.storage_location_id
    )
    return stock_take, storage_dto


async def claim_location_for_counting(
    db: AsyncSession,
    org_id: UUID,
    storage_location_id: UUID,
) -> tuple[list[UUID], list[UUID], dict[UUID, str]]:
    """Take the location's family locks, or refuse: one count per shelf.

    A count covers the location and every descendant, so the locks go on the
    whole family in a deterministic order -- an active count anywhere in the
    tree blocks a new one anywhere else in it, and the other way round.

    This belongs to the location rather than to whoever asked for the count:
    the scheduler creating a cycle count and a person creating one by hand
    are the same act as far as the shelf is concerned, and two passes over
    one shelf means two sets of corrections against the same stock.

    Returns the tree the caller is about to snapshot.
    """
    tree_ids, family_ids, location_paths = await get_storage_tree(
        db, org_id, storage_location_id
    )
    if not tree_ids:
        raise ServiceRejectionError('storage_not_found')

    for location_id in sorted(family_ids, key=str):
        await acquire_advisory_lock(db, f'stock_take:create:{location_id}')

    result = await db.execute(
        select(StockTake).where(
            StockTake.organization_id == org_id,
            StockTake.storage_location_id.in_(family_ids),
            StockTake.status == StockTakeStatus.IN_PROGRESS,
        )
    )
    if result.scalars().first():
        raise ServiceRejectionError('stock_take_active_for_location')
    return tree_ids, family_ids, location_paths


async def create_stock_take_from_storage(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    storage_location_id: UUID,
    name: str,
    description: str | None,
    notes: str | None,
    blind_mode: bool = False,
    tolerance_percent: Decimal | None = None,
    require_full_count: bool = True,
) -> StockTake:
    """Create a count and fill it with everything currently in the location.

    The count is recursive -- it covers the location and every descendant,
    so a rack is one pass instead of one per shelf. Claiming the location
    (see ``claim_location_for_counting``) raises if a count is already
    running anywhere in that tree.

    **The snapshot reads ``Item.quantity``, the record's own number.** The
    records are the stock, and the whole count is followed through on that
    one number: the staleness guard re-reads ``Item.quantity`` and refuses
    the finalization when it has moved, and the posting writes
    ``Item.quantity`` — the number the guard watched and the number the
    variance is stated against. Snapshot from one source and post into
    another, and the variance a counter is asked to explain is a gap the
    correction does not close, while the guard refuses counts over drift it
    has no way to describe.

    The group the records' view sums has no figure to offer instead: it is
    kept per ``(template, location)`` and several item rows can sit behind
    one, so it has no answer to "how much of this *record*" — the question
    a counted row asks.

    What the posting writes is settled per row: each counted record takes
    the counter's number and its difference is posted as a movement naming
    the count, so every group the count touched ends holding what its
    records add up to.
    """
    tree_ids, family_ids, location_paths = await claim_location_for_counting(
        db, org_id, storage_location_id
    )

    snapshot_entries: list[tuple[Any, str]] = []
    for location_id in tree_ids:
        items = await core_api.items.list_async(
            db,
            org_id,
            storage_location_id=location_id,
            limit=5000,
        )
        for item in items:
            snapshot_entries.append((item, location_paths[location_id]))

    stock_take = StockTake(
        user_id=user_id,
        organization_id=org_id,
        storage_location_id=storage_location_id,
        name=name,
        description=description,
        notes=notes,
        blind_mode=blind_mode,
        tolerance_percent=tolerance_percent,
        require_full_count=require_full_count,
        status=StockTakeStatus.IN_PROGRESS,
    )
    db.add(stock_take)
    await db.flush()

    for item, location_path in snapshot_entries:
        db.add(
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                item_brand=item.brand,
                uom_id=item.uom_id,
                # The record's own batch, so the list says which batch it
                # expects; the posting corrects that same batch.
                lot_id=item.lot_id,
                system_quantity=item.quantity,
                storage_location_id=item.location_id,
                location_in_storage=item.shelf_location or location_path,
            )
        )

    # A count opening is an act of its own: it claims a location tree and
    # freezes what the records held at that moment.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=stock_take.id,
        snapshot={
            'name': stock_take.name,
            'storage_location_id': str(storage_location_id),
            'items_count': len(snapshot_entries),
        },
    )
    await db.flush()
    await db.refresh(stock_take)
    return stock_take


async def calculate_stock_take_summary(
    stock_take_id: UUID, db: AsyncSession
) -> dict[str, Any]:
    """Count items, counted items, differences and progress percent.

    ``discrepancies_count`` is the number the completion dialog names —
    "overwrites the stock of N product(s)": every counted row that differs
    from the system, whether or not the tolerance spared it an explanation.
    ``is_discrepancy`` answers a different question ("beyond the tolerance —
    somebody must say why") and must not be read as "differs"; the list card
    and the report tile both have to agree with the dialog's N.
    """
    # Single query — count(*) FILTER instead of three separate counts.
    result = await db.execute(
        select(
            func.count().label('items_count'),
            func.count()
            .filter(StockTakeItem.counted_quantity.isnot(None))
            .label('counted_items_count'),
            func.count()
            .filter(
                StockTakeItem.counted_quantity.isnot(None),
                StockTakeItem.system_quantity.isnot(None),
                StockTakeItem.counted_quantity != StockTakeItem.system_quantity,
            )
            .label('discrepancies_count'),
        )
        .select_from(StockTakeItem)
        .where(StockTakeItem.stock_take_id == stock_take_id)
    )
    row = result.one()
    items_count = row.items_count or 0
    counted_items_count = row.counted_items_count or 0
    discrepancies_count = row.discrepancies_count or 0

    progress_percent = (
        (counted_items_count / items_count * 100) if items_count > 0 else 0.0
    )
    return {
        'items_count': items_count,
        'counted_items_count': counted_items_count,
        'discrepancies_count': discrepancies_count,
        'progress_percent': progress_percent,
    }


def calculate_discrepancy_stats(
    items: Sequence[StockTakeItem | StockTakeItemWithDetails],
) -> dict[str, int]:
    """Pure computation of report statistics from a list of counted items.

    "A perfect match" means what it says: counted equals the system, exactly.
    It used to be read off ``is_discrepancy`` — a flag that means "beyond the
    tolerance, somebody must explain it" — so a row the tolerance excused
    (2.1 counted against 2.3, −8.7% inside a 10% tolerance) was reported as
    a perfect match while the correction it produced sat in the ledger.
    ``is_discrepancy`` keeps its gating job; the report stops reading it as
    "agrees". A row that differs inside the tolerance is a
    ``tolerated_differences`` — accepted without an explanation, still
    counted, never hidden.
    """
    perfect_matches = sum(
        1
        for item in items
        if item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity == item.system_quantity
    )
    overstock = sum(
        1
        for item in items
        if item.is_discrepancy == 1
        and item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity > item.system_quantity
    )
    understock = sum(
        1
        for item in items
        if item.is_discrepancy == 1
        and item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity < item.system_quantity
    )
    tolerated_differences = sum(
        1
        for item in items
        if item.is_discrepancy == 0
        and item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity != item.system_quantity
    )
    not_counted = sum(1 for item in items if item.counted_quantity is None)
    return {
        'perfect_matches': perfect_matches,
        'overstock': overstock,
        'understock': understock,
        'tolerated_differences': tolerated_differences,
        'not_counted': not_counted,
    }


async def _started_by_name(db: AsyncSession, stock_take: StockTake) -> str | None:
    user = await core_api.users.get_async(
        db, stock_take.organization_id, stock_take.user_id
    )
    if user is None:
        return None
    return user.full_name or user.email


async def _as_reported(
    db: AsyncSession, stock_take: StockTake, items: list[StockTakeItem]
) -> list[StockTakeItemWithDetails]:
    """The count's rows as the report states them: shelf by shelf.

    A unit counted away from where its record stands is one row and two
    statements — none of it where it was expected, all of it where it was
    found — so the report says both: a shortage on the one shelf, a surplus
    on the other.
    """
    rows = [StockTakeItemWithDetails.model_validate(item) for item in items]
    if all(row.expected_location_id is None for row in rows):
        return rows
    _tree_ids, _family_ids, paths = await get_storage_tree(
        db, stock_take.organization_id, stock_take.storage_location_id
    )
    reported: list[StockTakeItemWithDetails] = []
    for row in rows:
        if row.expected_location_id is None or row.counted_quantity is None:
            reported.append(row)
            continue
        expected = row.system_quantity or Decimal('0')
        reported.append(
            row.model_copy(
                update={
                    'location_id': row.expected_location_id,
                    'shelf_location': paths.get(row.expected_location_id),
                    'counted_quantity': Decimal('0'),
                    'difference': -expected,
                }
            )
        )
        reported.append(
            row.model_copy(
                update={
                    'expected_location_id': None,
                    'system_quantity': Decimal('0'),
                    'difference': row.counted_quantity,
                }
            )
        )
    return reported


def _difference_of(item: StockTakeItem, record: ItemDTO | None) -> CountDifferenceDTO:
    """A counted row's difference, as the adjustment document's line states it.

    ``record`` is the row's item where it stands now. The line names the
    location the posting corrects: the shelf a unit counted elsewhere is
    moved to, else the one its record stands on — a shelf below the counted
    rack, or outside it for a record that left since the count opened.
    """
    assert item.item_id is not None and item.counted_quantity is not None
    return CountDifferenceDTO(
        item_id=item.item_id,
        location_id=(
            item.storage_location_id
            if item.expected_location_id is not None
            else record.location_id
            if record
            else None
        ),
        product_template_id=record.template_id if record else None,
        name=item.item_name,
        quantity_delta=item.counted_quantity - (item.system_quantity or Decimal('0')),
        uom_id=item.uom_id,
        batch_number=item.lot.name if item.lot is not None else None,
        # What the counter wrote. The reason code stays on the count's report,
        # which names it in the reader's language; the document page would
        # print the bare code.
        notes=item.discrepancy_reason,
    )


async def _post_the_differences(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    stock_take: StockTake,
    items: list[StockTakeItem],
    standing: dict[UUID, ItemDTO],
) -> tuple[str, UUID]:
    """Send what the count is about to change to the register as one document.

    Written in the posting's transaction, just before the count moves the
    stock it describes: the document is the office's record of the change,
    not a second posting of it. The rows are the ones the posting writes —
    counted, and not exactly what the record held — so a count that changes
    nothing leaves none. The count keeps the document's id.

    Returns the reference the posting's movements carry: the document when
    there is one, else the count itself.
    """
    differences = [
        _difference_of(
            item,
            standing.get(item.item_id)
            or await core_api.items.get_async(db, organization_id, item.item_id),
        )
        for item in items
        if item.item_id
        and item.counted_quantity is not None
        and item.counted_quantity != item.system_quantity
    ]
    recorded = await warehouse_api.record_count_differences_async(
        db,
        organization_id,
        user_id,
        location_id=stock_take.storage_location_id,
        differences=differences,
        reference=f'stock_take:{stock_take.id}',
        notes=stock_take.name,
    )
    if recorded is None:
        return 'adjustment', stock_take.id
    stock_take.adjustment_document_id = recorded[0]
    return 'document', recorded[0]


async def _adjustment_number(db: AsyncSession, stock_take: StockTake) -> str | None:
    """The number of the document this count's differences posted as, if any."""
    if stock_take.adjustment_document_id is None:
        return None
    summaries = await warehouse_api.get_target_summaries_by_ids_async(
        db, stock_take.organization_id, [stock_take.adjustment_document_id]
    )
    summary = summaries.get(stock_take.adjustment_document_id)
    return summary.number if summary is not None else None


async def build_stock_take_report(
    db: AsyncSession, stock_take: StockTake, storage_dto: StorageDTO | None = None
) -> StockTakeReport:
    """Build a StockTakeReport for a given stock take (used by both complete and report endpoints)."""
    result = await db.execute(
        select(StockTakeItem).where(StockTakeItem.stock_take_id == stock_take.id)
    )
    items: list[StockTakeItem] = list(result.scalars().all())
    reported = await _as_reported(db, stock_take, items)
    stats = calculate_discrepancy_stats(reported)
    summary = await calculate_stock_take_summary(stock_take.id, db)
    discrepancy_items = [item for item in reported if item.is_discrepancy == 1]
    tolerated_items = [
        item
        for item in reported
        if item.is_discrepancy == 0
        and item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity != item.system_quantity
    ]

    return StockTakeReport(
        stock_take_id=stock_take.id,
        stock_take_name=stock_take.name,
        location_name=storage_dto.name if storage_dto else '',
        status=stock_take.status,
        started_at=stock_take.started_at,
        completed_at=stock_take.completed_at,
        started_by_name=await _started_by_name(db, stock_take),
        total_items=summary['items_count'],
        counted_items=summary['counted_items_count'],
        discrepancies=summary['discrepancies_count'],
        progress_percent=summary['progress_percent'],
        perfect_matches=stats['perfect_matches'],
        overstock=stats['overstock'],
        understock=stats['understock'],
        tolerated_differences=stats['tolerated_differences'],
        not_counted=stats['not_counted'],
        all_items=reported,
        discrepancy_items=discrepancy_items,
        tolerated_items=tolerated_items,
        closed_locations=await list_closed_locations(db, stock_take.id),
        adjustment_document_id=stock_take.adjustment_document_id,
        adjustment_document_number=await _adjustment_number(db, stock_take),
    )


async def _refuse_a_count_that_cannot_be_posted(
    db: AsyncSession,
    organization_id: UUID,
    locked_stock_take: StockTake,
    complete_data: StockTakeComplete,
    items: list[StockTakeItem],
) -> tuple[dict[UUID, ItemDTO], int, int]:
    """Every way a count can be refused, before a single number is written.

    The questions come in the order they matter: whether the day may be
    posted at all, whether anybody is still waiting to have a row counted
    again, whether the counted rows are still statements about the shelf, and
    only then whether each difference is explained, inside the tolerance and
    inside the cap. Returns the shelf as it stands today — the read the
    posting settles the shelf on — and how many rows the caller may accept
    past each of the two thresholds, which is what the audit entry names.
    """
    # Respect the inventory period lock — finalizing with adjustments
    # writes back via core_api.items.update_quantity_async which itself
    # re-checks, but the explicit pre-loop check gives a clear 409
    # even if finalize is called before any write.
    # The organization's day, not the server's: which month a count
    # falls in decides whether it may be posted at all.
    await core_api.periods.check_not_closed_async(
        db,
        organization_id,
        await core_api.organizations.today_async(db, organization_id),
    )
    # A row waiting to be counted again is not a row anybody has
    # finished with. Posting it would make the recount pointless: the
    # stock would already hold the number somebody asked to have checked.
    awaiting = [
        {'item_id': str(item.item_id), 'item_name': item.item_name}
        for item in items
        if item.recount_requested
    ]
    if awaiting:
        raise ConflictException(
            code='STOCK_TAKE_AWAITING_RECOUNT',
            message=get_error_message(
                'stock_take_awaiting_recount',
                get_current_lang(),
                count=len(awaiting),
            ),
            details={'awaiting_recount_items': awaiting},
        )

    # Before any of the questions about the differences: are they still
    # differences? A row counted against a quantity the shelf no longer
    # has is a statement about a state that has passed, and asking
    # whether it was explained or whether it is inside the tolerance
    # asks the wrong thing about the wrong number. The shelf read here
    # is the one the posting settles the shelf on, further down.
    standing = await _the_shelf_today(db, organization_id, locked_stock_take)
    await _refuse_if_the_stock_moved(
        db, organization_id, locked_stock_take, items, standing
    )

    # Why before who: a difference nobody has explained cannot be
    # accepted at all, so that refusal comes first and names the rows.
    # Only once every one of them says what happened does the question
    # become whether this person may accept them.
    over_tolerance = _rows_over_tolerance(locked_stock_take, items)
    unexplained = [row for row in over_tolerance if not row['reason_code']]
    if unexplained:
        raise ConflictException(
            code='STOCK_TAKE_TOLERANCE_REASON_MISSING',
            message=get_error_message(
                'stock_take_tolerance_reason_missing',
                get_current_lang(),
                count=len(unexplained),
            ),
            details={'unexplained_items': unexplained},
        )
    if over_tolerance and not complete_data.force_over_tolerance:
        raise ConflictException(
            code='STOCK_TAKE_OVER_TOLERANCE',
            message=get_error_message(
                'stock_take_over_tolerance',
                get_current_lang(),
                count=len(over_tolerance),
            ),
            details={'over_tolerance_items': over_tolerance},
        )
    over_tolerance_accepted = (
        len(over_tolerance) if complete_data.force_over_tolerance else 0
    )

    over_cap = _rows_over_cap(items)
    if over_cap and not complete_data.force_over_cap:
        raise ConflictException(
            code='STOCK_TAKE_OVER_CAP',
            message=get_error_message(
                'stock_take_over_cap', get_current_lang(), count=len(over_cap)
            ),
            details={'over_cap_items': over_cap},
        )
    over_cap_accepted = len(over_cap) if complete_data.force_over_cap else 0

    return standing, over_tolerance_accepted, over_cap_accepted


async def finalize_stock_take(
    db: AsyncSession,
    stock_take: StockTake,
    complete_data: StockTakeComplete,
    organization_id: UUID,
    user_id: UUID,
    storage_dto: StorageDTO | None = None,
) -> StockTakeReport:
    """Validate, optionally apply adjustments, mark COMPLETED and return a StockTakeReport."""
    # Lock the stock take row to prevent concurrent finalize races.
    #
    # ``populate_existing`` because this row is already in the identity map —
    # the caller loaded it to check permissions — and a locking select hands
    # back the instance it finds there without refreshing its columns. The
    # status check below then read the status from before the lock was
    # granted, which is exactly the value a concurrent finalize has just
    # changed: both callers saw IN_PROGRESS, both went through, and the
    # organization log held the count twice.
    result = await db.execute(
        select(StockTake)
        .where(StockTake.id == stock_take.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked_stock_take = result.scalars().first()
    if not locked_stock_take:
        raise catalogue_refusal('stock_take_not_found')

    if locked_stock_take.status != StockTakeStatus.IN_PROGRESS:
        raise catalogue_refusal('stock_take_not_active')

    count_result = await db.execute(
        select(func.count())
        .select_from(StockTakeItem)
        .where(
            StockTakeItem.stock_take_id == locked_stock_take.id,
            StockTakeItem.counted_quantity.is_(None),
        )
    )
    uncounted = int(count_result.scalar() or 0)
    # require_full_count controls whether every
    # item must be counted before finalize. Partial counts (and cycle
    # counts, which set the flag to False) close without the gate.
    if locked_stock_take.require_full_count and uncounted > 0:
        raise catalogue_refusal('stock_take_uncounted_items', count=uncounted)

    items_result = await db.execute(
        select(StockTakeItem).where(StockTakeItem.stock_take_id == locked_stock_take.id)
    )
    items: list[StockTakeItem] = list(items_result.scalars().all())
    adjusted_items = 0
    over_cap_accepted = 0
    over_tolerance_accepted = 0

    if complete_data.apply_adjustments:
        (
            standing,
            over_tolerance_accepted,
            over_cap_accepted,
        ) = await _refuse_a_count_that_cannot_be_posted(
            db, organization_id, locked_stock_take, complete_data, items
        )

        # What every shelf this count touched has to hold, worked out before
        # anything is written: the difference is settled on those numbers,
        # and the holds that no longer have stock behind them give way first.
        postings = _shelf_postings(items, standing)
        # Every group this count settles is locked first, in one order: the
        # anchors those groups stand on, before the first write. The record
        # writes below carry their deltas into the movement ledger through
        # their own posting, and an operation that writes more than one group
        # locks them all first (AGENTS.md, Stock Posting Rules).
        await core_api.stock.lock_async(
            db,
            organization_id,
            keys=sorted(
                (posting.template_id, posting.location_id) for posting in postings
            ),
        )
        for posting in postings:
            await _release_what_the_shelf_no_longer_covers(
                db,
                organization_id,
                posting.template_id,
                posting.location_id,
                posting.leaving_quantity,
            )

        # One document in the register for everything the loop below writes,
        # and the movements name it: the ledger, the document and the count
        # tell one story. With no document the movements name the count.
        reference_type, reference_id = await _post_the_differences(
            db, organization_id, user_id, locked_stock_take, items, standing
        )
        for item in items:
            if not item.item_id or item.counted_quantity is None:
                continue
            if item.expected_location_id is not None and item.storage_location_id:
                # A unit that owns its identity, found on another shelf: its
                # record goes where it was counted, and the quantity below
                # is settled there.
                adjusted_items += 1
                await core_api.items.transfer_async(
                    db,
                    organization_id,
                    item.item_id,
                    item.storage_location_id,
                    user_id=user_id,
                    history_changes={
                        'reason': 'stock_take_adjustment',
                        'stock_take_id': str(locked_stock_take.id),
                    },
                )
            # A row counted exactly as the system holds it changed nothing.
            # Writing it anyway produced an organization-log entry saying
            # "500 -> 500" — a change that never happened, indistinguishable
            # from a manual edit made in the same second.
            if (
                item.system_quantity is not None
                and item.counted_quantity == item.system_quantity
            ):
                continue
            if item.expected_location_id is None:
                adjusted_items += 1
            # A count is the truth about the shelf, and a hold is a promise
            # about it. Where the shelf turns out not to cover the promise,
            # the promise is what gives way — right for a dispatch, which
            # must not eat into another document's claim. The release above
            # is the shelf's, the way the holds are, and it runs before
            # these writes: a shelf counted down has to stop promising what
            # it no longer holds before its own records say so.
            #
            # Why the shelf disagreed with the records travels with the
            # correction. Kept only on the count, it answered the question
            # for whoever opened that count and nobody else — and the
            # product's own history is where a person looks first when a
            # quantity has moved without a document.
            history_changes: dict[str, Any] = {
                'reason': 'stock_take_adjustment',
                'stock_take_id': str(locked_stock_take.id),
                **(
                    {'discrepancy_reason_code': item.discrepancy_reason_code}
                    if item.discrepancy_reason_code
                    else {}
                ),
                **(
                    {'discrepancy_reason': item.discrepancy_reason}
                    if item.discrepancy_reason
                    else {}
                ),
            }
            if item.item_id in standing:
                # The record moves, and its posting writes the same delta as
                # its movement and its cost layer, in this one transaction
                # and under the group's anchor lock. The delta is this
                # record's own (what the counter saw minus what its record
                # said), so the count never reads the ledger it writes to: a
                # mismatch the ledger was already carrying travels with it,
                # neither cured nor widened. A batch the counter named goes
                # with it: a record that names none learns which it holds.
                await core_api.items.update_quantity_async(
                    db,
                    organization_id,
                    item.item_id,
                    item.counted_quantity,
                    user_id=user_id,
                    history_changes=history_changes,
                    lot_id=item.lot_id,
                    # The ledger has to say this was the count, not a
                    # quantity somebody typed in by hand.
                    move_reference_type=reference_type,
                    move_reference_id=reference_id,
                )
                continue
            # A row whose item left the counted shelf since the snapshot is
            # not the shelf's to settle: its difference belongs where the
            # item stands now, so it keeps the record's own posting — which lands
            # it there, batch and all — and that shelf is the one whose holds
            # give way for a shortage.
            moved_away = await core_api.items.get_async(
                db, organization_id, item.item_id
            )
            await _release_what_the_shelf_no_longer_covers(
                db,
                organization_id,
                moved_away.template_id if moved_away else None,
                moved_away.location_id if moved_away else None,
                max(
                    Decimal('0'),
                    Decimal(str(item.system_quantity or 0)) - item.counted_quantity,
                ),
            )
            # A row that named a batch corrects that batch. Without the lot
            # the write lands on whatever batch the record itself carries —
            # none at all on a record that names none — so the column the
            # counter filled in changed nothing at all.
            await core_api.items.update_quantity_async(
                db,
                organization_id,
                item.item_id,
                item.counted_quantity,
                user_id=user_id,
                history_changes=history_changes,
                lot_id=item.lot_id,
                move_reference_type=reference_type,
                # The ledger holds the correction; without this it holds only
                # the product it landed on, and a count's adjustment reads
                # exactly like a quantity somebody typed in by hand. The
                # reference is the count's document (or the count), so the
                # movement history can say on whose instruction it moved.
                move_reference_id=reference_id,
            )

    locked_stock_take.status = StockTakeStatus.COMPLETED
    locked_stock_take.completed_at = datetime.now(UTC)
    if complete_data.notes:
        locked_stock_take.notes = (
            (locked_stock_take.notes or '') + '\n' + complete_data.notes
        )

    # "Somebody counted the fridge on Monday" is an event of its own. Without
    # it the log held only the consequences — quantity changes that read like
    # manual edits, and nothing at all when every count matched.
    counted_items = sum(1 for item in items if item.counted_quantity is not None)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.STOCK_TAKE,
        target_id=locked_stock_take.id,
        snapshot={
            'name': locked_stock_take.name,
            'counted_items': counted_items,
            'adjusted_items': adjusted_items,
            'over_cap_accepted': over_cap_accepted,
            'over_tolerance_accepted': over_tolerance_accepted,
        },
    )

    await db.flush()

    reported = await _as_reported(db, locked_stock_take, items)
    stats = calculate_discrepancy_stats(reported)
    discrepancy_items = [item for item in reported if item.is_discrepancy == 1]
    tolerated_items = [
        item
        for item in reported
        if item.is_discrepancy == 0
        and item.counted_quantity is not None
        and item.system_quantity is not None
        and item.counted_quantity != item.system_quantity
    ]

    return StockTakeReport(
        stock_take_id=locked_stock_take.id,
        stock_take_name=locked_stock_take.name,
        location_name=storage_dto.name if storage_dto else '',
        status=locked_stock_take.status,
        started_at=locked_stock_take.started_at,
        completed_at=locked_stock_take.completed_at,
        started_by_name=await _started_by_name(db, locked_stock_take),
        total_items=len(items),
        # What somebody actually counted, not how many rows the count had.
        # A partial count is an ordinary thing — a cycle count is one by
        # definition — and this page used to say twelve of twelve at a
        # hundred per cent directly above "three not counted".
        counted_items=counted_items,
        # The rows the count just overwrote — the same number the
        # confirmation dialog named before anybody pressed the button.
        discrepancies=adjusted_items,
        progress_percent=((counted_items / len(items) * 100) if items else 0.0),
        perfect_matches=stats['perfect_matches'],
        overstock=stats['overstock'],
        understock=stats['understock'],
        tolerated_differences=stats['tolerated_differences'],
        not_counted=uncounted,
        all_items=reported,
        discrepancy_items=discrepancy_items,
        tolerated_items=tolerated_items,
        closed_locations=await list_closed_locations(db, locked_stock_take.id),
        adjustment_document_id=locked_stock_take.adjustment_document_id,
        adjustment_document_number=await _adjustment_number(db, locked_stock_take),
    )
