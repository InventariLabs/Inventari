from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError, StockUnavailableError
from app.core.logging import get_logger
from app.core.txn_memo import records_locked
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.stock_move import StockMoveReferenceType
from app.schemas.validators import QUANTITY_MAX
from app.services._stock_draw import free_in_grain_async, records_by_grain_async
from app.services._stock_quant_ops import _refuse, lock_stock_async
from app.services._stock_quant_query import assert_lot_consumable_async

logger = get_logger(__name__)


async def _adopt_card_async(
    db: AsyncSession, item: Item, *, user_id: UUID | None
) -> UUID:
    """Give a record that predates its card the card its ledger writes need.

    The record's own words resolve — or mint — the card, the same rule the
    create path applies to every record that opens: two records of one
    hand-named product land on one card instead of minting twins. The bind
    takes the unit gate every other door takes, so a record kept in another
    unit is refused by name rather than relabelled.

    Returns the adopted card's id. The link is written here (and a missing
    unit taken from the card, see ``bind_item_to_template_async``): what the
    record holds is not this helper's to post — see
    :func:`post_opening_balance_async` — and the caller's own delta is the
    movement.
    """
    from app.core.public_api import core_api

    adopted = await core_api.product_templates.resolve_default_async(
        db,
        item.organization_id,
        name=item.name,
        brand=item.brand,
        barcode=item.barcode,
        uom_id=item.uom_id,
    )
    bound = await core_api.items.bind_template_async(
        db, item.organization_id, item.id, adopted.id, user_id=user_id
    )
    if bound is None:
        raise ServiceRejectionError('item_not_found')
    return adopted.id


async def post_opening_balance_async(
    db: AsyncSession,
    item: Item,
    *,
    template_id: UUID,
    quantity: Decimal,
    user_id: UUID | None,
    location_id: UUID | None = None,
    sync_valuation: bool = True,
) -> None:
    """Put the stock a record already holds into the ledger it just joined.

    A record that predates its card keeps its stock outside the register —
    no movement, no cost layer — and joining the register means saying what
    it holds, the way the ``openbal01`` migration said it for every shelf the
    register did not know: a movement marked ``opening_balance`` the shelf
    can be traced back to, and the layer the reconciliation report measures
    the shelf against, posted the way a quantity raised by hand is: at the
    organization's own rate, marked ``unknown`` where there is none.

    Without the movement the shelf and the ledger tell different stories
    from the adoption on — the report's shelf-versus-ledger pair — and
    without the layer the pair *(card, location)* and the value behind it
    do; a caller that owns its valuation writes (``sync_valuation=False``)
    keeps owning this one too.

    The one place this rule is written. Every door that gives a record its
    card posts the opening here — the core's edit and quantity paths, and
    the documents executor through ``core_api.items`` — so a change to what
    an opening writes cannot reach one door and miss another; it used to be
    written twice, once per side.

    *quantity* is what the record held before the door changed it, in the
    record's own unit, and lands in the card's. *location_id* is the shelf
    it is posted on; left out, the record's own. A door whose record names
    no shelf says where the stock stands — the documents executor passes the
    shelf it is taking from — and with no shelf at all nothing is posted.
    """
    from app.services.stock_moves_service import create_async as create_move_async
    from app.services.uom_service import to_stock_uom_async
    from app.services.valuation_service import ValuationService

    location_id = location_id or item.storage_location_id
    if quantity <= 0 or location_id is None:
        return
    stock_quantity = await to_stock_uom_async(
        db, item.organization_id, template_id, quantity, item.uom_id
    )
    await create_move_async(
        db,
        organization_id=item.organization_id,
        product_template_id=template_id,
        to_location_id=location_id,
        quantity=stock_quantity,
        owner_id=item.owner_id,
        reference_type=StockMoveReferenceType.OPENING_BALANCE,
        reference_id=item.id,
        created_by=user_id,
    )
    if sync_valuation:
        await ValuationService.record_receipt_by_id_async(
            db, item.organization_id, template_id, stock_quantity, None
        )


async def adopt_card_with_opening_async(
    db: AsyncSession,
    item: Item,
    *,
    holding: Decimal,
    user_id: UUID | None,
    sync_valuation: bool = True,
) -> UUID:
    """Bring a record that predates its card into the register, card first.

    The two steps every core door takes for such a record, in the only
    order that works: the card the ledger is keyed by, then the stock the
    record already held — *holding*, read before the door changes it —
    posted on the record's shelf as an opening. A door that needs a card
    for its own reasons (the edit that writes a threshold to it) takes the
    register along with it; one that skipped the opening left the record
    saying what the shelf did not.

    Returns the adopted card's id.
    """
    template_id = await _adopt_card_async(db, item, user_id=user_id)
    await post_opening_balance_async(
        db,
        item,
        template_id=template_id,
        quantity=holding,
        sync_valuation=sync_valuation,
        user_id=user_id,
    )
    return template_id


#: The outflows that consume the goods. Only these must find the batch
#: active; throwing a recalled batch away is what a recall asks for, and a
#: plain quantity edit corrects the record rather than releasing stock.
_CONSUMING = frozenset({ItemAction.USED.value})


async def _refuse_a_short_named_batch_async(
    db: AsyncSession,
    item: Item,
    template_id: UUID,
    lot_id: UUID,
    take: Decimal,
) -> None:
    """Refuse a shortage counted on one batch that the batch cannot give.

    A count that names its batch corrects that batch and no other: the
    removal strategy would pick by expiry or age and could take it off the
    goods the counter did not look at. So a batch without a record on the
    shelf, or one whose reservation rows would be left standing on less than
    they hold, is an error rather than a reason to reach for another.
    Asked after the record's new number is set, like every grain check here.
    """
    location_id = item.storage_location_id
    grain = (location_id, lot_id, item.owner_id)
    left = await free_in_grain_async(db, item.organization_id, template_id, grain)
    if left >= 0:
        return
    on_hand = await records_by_grain_async(
        db, item.organization_id, template_id, location_id
    )
    if grain not in on_hand:
        raise await _refuse(
            db,
            StockUnavailableError.NO_STOCK,
            'stock_none_at_location',
            template_id,
            location_id,
        )
    raise await _refuse(
        db,
        StockUnavailableError.NOT_ENOUGH,
        'stock_not_enough',
        template_id,
        location_id,
        available=max(left + take, Decimal('0')),
        requested=take,
    )


async def _post_the_change_async(
    db: AsyncSession,
    item: Item,
    old_quantity: Decimal | None,
    new_quantity: Decimal | None,
    *,
    sync_valuation: bool = True,
    unit_cost: Decimal | None = None,
    outflow_reason: str | None = None,
    lot_id: UUID | None = None,
    move_reference_type: str = 'item',
    move_reference_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """Write the movement and the cost of a change to a record's number.

    The record is the state — per card, shelf, batch and owner, summed by
    ``stock_quants_from_records`` — ``StockMove`` is the journal that
    explains every change to it, and the valuation layers say what it cost.
    This posting writes the other two on every quantity change path (create,
    update, consume, discard, scan, import). Every organization keeps the
    register, whatever modules it has enabled.
    Whether the register's screens are offered is a separate question, asked
    where the screens are.

    A record that predates its card is not turned away: the card is adopted
    from the record's own words and the stock it already held is posted as
    an opening, so the change the caller asked for lands in the register the
    same way it does for a record that always had one. The one no-op that
    remains has nothing to write to: a record that names no shelf.

    When *sync_valuation* is True (default), a receipt is also recorded in the
    StockValuationLayer.  *unit_cost* controls the cost basis of that receipt:
    when provided (e.g. ``item.purchase_price`` on manual create) the stock is
    valued at that cost; otherwise the organization's own rate applies.  Set
    *sync_valuation* to False when the caller already records valuation
    (e.g. document executor).

    The movement names the record's own batch (``Item.lot_id``). *lot_id* is
    for a caller that counted a batch and names it — that batch then takes
    the change in both directions, and a shortage on it is an error rather
    than a reason to reach for another (see
    :func:`_refuse_a_short_named_batch_async`). *move_reference_type* lets
    such a caller say what the resulting movement was; the default still
    reads as a one-off edit to the record. *move_reference_id* says which
    one — the stock take a correction came out of, say. Without it the
    movement points at the item it changed, which answers "what moved" and
    never "on whose instruction": a correction posted by a count and a
    quantity typed in by hand read the same in the ledger.

    *outflow_reason* is why the stock is leaving, where the caller knows it —
    only ``_reduce_quantity`` does, since only it distinguishes a use from a
    disposal. It ends up on the outgoing valuation layer, which is what lets
    the waste report tell one from the other, and a use or a consumption
    must find the record's batch ACTIVE: throwing a recalled batch away is
    what a recall asks for, eating it is not. A plain quantity edit passes
    nothing: nobody said why, so the ledger must not claim to know.
    """
    if item.storage_location_id is None:
        return

    old = old_quantity or Decimal('0')
    new = new_quantity or Decimal('0')
    delta = new - old

    if delta == 0:
        return

    from app.services.stock_moves_service import create_async as create_move_async
    from app.services.valuation_service import ValuationService

    org_id: UUID = item.organization_id
    location_id: UUID = item.storage_location_id
    template_id = item.template_id
    if template_id is None:
        # A record that predates its card held its stock nowhere but on
        # itself, and this write — whose ledger is kept per card — had no
        # place to put any of it: the number on the record moved, the shelf
        # stood still, and the register stayed empty. The card comes first,
        # the same resolve-or-mint-and-bind the document doors run, and the
        # stock the record already held is posted as an opening, so the
        # shelf starts from what the record says it holds and the delta
        # below is the change's own movement, told apart from the opening.
        template_id = await adopt_card_with_opening_async(
            db, item, holding=old, user_id=user_id, sync_valuation=sync_valuation
        )
    abs_delta = abs(delta)
    named_lot = lot_id
    lot_id = named_lot if named_lot is not None else item.lot_id

    if delta > 0:
        if sync_valuation:
            # A cost of zero or none is no price: the receipt is then valued
            # at the organization's own rate (unpriced).
            await ValuationService.record_receipt_by_id_async(
                db,
                org_id,
                template_id,
                delta,
                unit_cost if unit_cost is not None and unit_cost > 0 else None,
            )
        # The movement explains the change: analytics, FIFO/FEFO history,
        # aging and traceability read it.
        await create_move_async(
            db,
            organization_id=org_id,
            product_template_id=template_id,
            to_location_id=location_id,
            quantity=delta,
            lot_id=lot_id,
            owner_id=item.owner_id,
            reference_type=move_reference_type,
            reference_id=move_reference_id or item.id,
            created_by=user_id,
        )
        return

    if named_lot is not None:
        # Counting is not consuming, so a batch on hold may still be
        # corrected — but only out of what it has.
        await _refuse_a_short_named_batch_async(
            db, item, template_id, named_lot, abs_delta
        )
    elif item.lot_id is not None and outflow_reason in _CONSUMING:
        await assert_lot_consumable_async(db, item.lot_id, org_id)
    if sync_valuation:
        await ValuationService.post_delivery_by_id_async(
            db,
            org_id,
            template_id,
            abs_delta,
            reason=outflow_reason,
            item_id=item.id,
        )
    await create_move_async(
        db,
        organization_id=org_id,
        product_template_id=template_id,
        from_location_id=location_id,
        quantity=abs_delta,
        lot_id=lot_id,
        owner_id=item.owner_id,
        reference_type=move_reference_type,
        reference_id=move_reference_id or item.id,
        created_by=user_id,
    )


#: What a change to a record's number depends on: the number itself, and the
#: grain it belongs to.
_RECORD_GRAIN = ['quantity', 'template_id', 'storage_location_id', 'lot_id', 'owner_id']


async def lock_record_stock_async(
    db: AsyncSession, item: Item, *, read_again: Sequence[str] = _RECORD_GRAIN
) -> None:
    """Lock the stock a change to *item* writes, then read the record under the lock.

    The group's anchor comes first — every writer of the group takes it,
    so while it is held nobody else changes the group's records or its
    holds — and then the record's own row, which is the only lock a record
    without a card has (no card, no group, no anchor). The row is taken
    ``FOR NO KEY UPDATE``: a document line's foreign key to the record only
    needs the key to stay, and a stronger lock made the two wait on each
    other.

    The number is read again under the lock. A door that works out the new
    number from the old one — a consumption, a rescan — read the old one
    before anybody locked anything, so two hands each took off the number
    both had seen. Such a door calls this before it reads ``item.quantity``.
    *read_again* names what is read again — the record's number and grain
    by default. The posting reads only the number, since its caller may have
    set the record's batch or shelf just before; a caller that already knows
    the number it replaces reads nothing and takes the anchor alone.
    """
    if item.template_id is not None and item.storage_location_id is not None:
        await lock_stock_async(
            db,
            item.organization_id,
            keys=[(item.template_id, item.storage_location_id)],
        )
    held = records_locked(db)
    if (item.organization_id, item.id) in held:
        # Already read under this transaction's lock, and nobody else can
        # change it while it is held: what the record says is still true.
        return
    if read_again and sa_inspect(item).persistent:
        await db.refresh(
            item, attribute_names=read_again, with_for_update={'key_share': True}
        )
        held.add((item.organization_id, item.id))


async def _refuse_what_the_grain_cannot_give_async(
    db: AsyncSession, item: Item, take: Decimal
) -> None:
    """Refuse a decrease that left the record's grain holding less than its holds.

    The grain is the record's shelf, batch and owner. Asked after the
    record's new number is set, so it does not matter whether the door wrote
    the number itself before posting the change (an edit does) or left it to
    the posting: what the grain's records hold now, less what its reservation
    rows hold, must not be below zero. Taking more would leave an order's
    hold standing on stock that is gone; the change is refused by name
    instead of being found in another batch, and the caller's transaction
    takes the number back.
    """
    if item.template_id is None or item.storage_location_id is None:
        return
    grain = (item.storage_location_id, item.lot_id, item.owner_id)
    left = await free_in_grain_async(db, item.organization_id, item.template_id, grain)
    if left < 0:
        raise await _refuse(
            db,
            StockUnavailableError.NOT_ENOUGH,
            'stock_not_enough',
            item.template_id,
            item.storage_location_id,
            available=max(left + take, Decimal('0')),
            requested=take,
        )


async def apply_quantity_change_async(
    db: AsyncSession,
    item: Item,
    new_quantity: Decimal,
    *,
    old_quantity: Decimal | None = None,
    sync_valuation: bool = True,
    post_the_change: bool = True,
    unit_cost: Decimal | None = None,
    outflow_reason: str | None = None,
    lot_id: UUID | None = None,
    move_reference_type: str = 'item',
    move_reference_id: UUID | None = None,
    user_id: UUID | None = None,
) -> Decimal:
    """Atomically set item.quantity and write its movement and its cost.

    Returns the old quantity so callers can use it for history/auditing.

    Prefer this helper over direct ``item.quantity = ...`` assignments.
    It keeps the ledger and the cost layers in step with the record and
    prevents the common bug of forgetting to call ``_post_the_change_async``
    after a quantity change.

    *unit_cost* is forwarded to ``_post_the_change_async`` to value positive
    deltas (receipts); pass ``item.purchase_price`` so manual creates are
    valued at their real cost instead of fabricating a zero-cost layer.

    *outflow_reason* does the same for negative ones: it names why the stock
    left, and travels onto the outgoing valuation layer.

    *lot_id*, *move_reference_type* and *move_reference_id* are forwarded to
    the posting — see ``_post_the_change_async``.

    The change is written under the group's anchor, with the record read
    again under it when the caller did not name *old_quantity* (see
    :func:`lock_record_stock_async`). A decrease the record's grain cannot
    give without eating an order's hold is refused (``StockUnavailableError``)
    before anything is written.

    *user_id* is who did this. The ledger has a column for it and the item
    paths left it empty, so every movement a person made through the
    application read as nobody's — the one question a movement history exists
    to answer. Optional because a background path genuinely has no author.
    """
    # The ceiling stands on the writer, not on one more input schema: this
    # helper is every door's last step to the column, named doors (the
    # quantity PATCH) and built ones (a stock take's counted quantity, the
    # bridges that state records through the service) alike. A value past
    # what numeric(12, 3) stores is refused with the bound named, where the
    # driver would have answered with an overflow.
    if new_quantity > QUANTITY_MAX:
        raise ServiceRejectionError(
            'item_quantity_above_ceiling',
            quantity=new_quantity,
            ceiling=QUANTITY_MAX,
        )
    await lock_record_stock_async(
        db, item, read_again=['quantity'] if old_quantity is None else []
    )
    old = old_quantity if old_quantity is not None else item.quantity
    item.quantity = new_quantity
    # A batch the caller counted and names is not the record's grain: the
    # count corrects that batch, and counting is not taking.
    if post_the_change and lot_id is None and old is not None and new_quantity < old:
        await _refuse_what_the_grain_cannot_give_async(db, item, old - new_quantity)
    if post_the_change:
        await _post_the_change_async(
            db,
            item,
            old,
            new_quantity,
            sync_valuation=sync_valuation,
            unit_cost=unit_cost,
            outflow_reason=outflow_reason,
            lot_id=lot_id,
            move_reference_type=move_reference_type,
            move_reference_id=move_reference_id,
            user_id=user_id,
        )
    return old or Decimal('0')
