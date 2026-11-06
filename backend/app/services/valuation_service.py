"""
AVCO Valuation Service.

Provides Average Cost (AVCO) valuation for inventory.
Each inventory receipt creates a StockValuationLayer.
Delivery consumes layers FIFO (oldest first).
AVCO rate = sum(layers.value) / sum(layers.remaining_qty)

Note: this is a Core service writing to the Core-owned ``StockValuationLayer``
model. It is exposed to modules via ``core_api.valuation`` (read+write), so it
is NOT a module escape-hatch — the ``# architecture: allow_direct_db_access``
marker (reserved for modules needing read-only Core access) does not apply here.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, Select, distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.money import quantise
from app.core.posting_batch import current_batch
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

logger = get_logger(__name__)

#: Decimals a cost keeps. ``StockValuationLayer.unit_cost`` is
#: ``Numeric(12, 4)``, and a rate rounded to two threw away what the column
#: was widened to hold: a spice at 0.0234 per gram came back as 0.02, and
#: anything under half a grosz per unit came back as zero — the one answer
#: :class:`CostBasis` exists to keep apart from "nobody said a price".
COST_PLACES = 4


@dataclass(frozen=True)
class DeliveryPosting:
    """What an outflow took off the books.

    ``cost`` is what the consumed layers were worth — the figure the outgoing
    row is written at. It is ``None`` when the layers could not say: they did
    not cover the move, or they disagree on a currency. A caller pricing what
    the outflow produced (a production run valuing its output) needs that
    difference; a caller that only moves stock does not, and keeps taking the
    consumed layers.
    """

    consumed_layers: list['StockValuationLayer']
    cost: Decimal | None


async def _organization_currency(db: AsyncSession, organization_id: UUID) -> str | None:
    """What this organization keeps its books in, or None if it never said."""
    return await db.scalar(
        select(Organization.currency).where(Organization.id == organization_id)
    )


async def _template_for_organization(
    db: AsyncSession, organization_id: UUID, product_template_id: UUID
) -> ProductTemplate | None:
    """The product card, if it is global or the organization's own.

    Read by statement, which also settles the relationships of a card already
    in the session; inside a posting the card is in hand and is found by
    identity, a statement a line saved.
    """
    if current_batch(db) is not None:
        template = await db.get(ProductTemplate, product_template_id)
        if template is None or template.organization_id not in (organization_id, None):
            return None
        return template
    return await db.scalar(
        select(ProductTemplate).where(
            ProductTemplate.id == product_template_id,
            (ProductTemplate.organization_id == organization_id)
            | (ProductTemplate.organization_id.is_(None)),
        )
    )


def _fifo_order() -> tuple[Any, ...]:
    """The order layers are drained in, oldest first.

    FIFO in business-date order: the date the receipt is about (its
    document's scheduled date) decides who is oldest, and a booking typed
    late cannot push the goods it describes to the back of the queue. Layers
    with no document behind them fall back to their write time; created_at
    then id breaks the ties a same-day batch of receipts would otherwise
    leave to chance.
    """
    return (
        func.coalesce(
            StockValuationLayer.document_date,
            func.cast(StockValuationLayer.created_at, Date),
        ).asc(),
        StockValuationLayer.created_at.asc(),
        StockValuationLayer.id.asc(),
    )


def _open_layers(
    organization_id: UUID,
    template_ids: Iterable[UUID],
    reverses_line_id: UUID | None = None,
) -> Select[Any]:
    """The layers a delivery of these products drains, locked, in the order they go.

    One product in one organization, not one shelf — see the lock below.
    """
    return (
        select(StockValuationLayer)
        .where(
            StockValuationLayer.product_template_id.in_(list(template_ids)),
            # Layers are org-owned even for global templates: delivery
            # must consume only the caller's own layers.
            StockValuationLayer.organization_id == organization_id,
            StockValuationLayer.remaining_qty > 0,
            StockValuationLayer.direction == 'IN',
        )
        .order_by(
            # The product's own queue; across products the order is by product.
            StockValuationLayer.product_template_id,
            # The layer these goods arrived on, when the caller can name
            # it, before anything else. ``False`` sorts before ``True``,
            # so a query with no line to reverse orders every row alike
            # and the FIFO below decides on its own.
            (StockValuationLayer.document_line_id != reverses_line_id)
            if reverses_line_id is not None
            else literal(False),
            *_fifo_order(),
        )
        # Hold the rows while they are drained. Reading a remainder and
        # writing it back is not safe on its own, and the anchor locks do
        # not protect this: they lock per location, while a layer belongs
        # to a product. Two outflows of the same goods from two different
        # shelves therefore read the same layer, each found it sufficient,
        # and one of the two writes survived — the books lost less than
        # the shelf did. Locked in the order they are consumed, which is
        # what keeps two of these from deadlocking against each other.
        # Named, not bare: the query alongside this one in the reservation
        # service took a bare lock, grew an outer join, and could not run
        # at all.
        #
        # One product in one organization, not one shelf — and that grain
        # is a choice (ADR-020), not an accident. A layer records what a
        # product cost and carries no location, so the product is the
        # narrowest row this lock can name; two outflows of the same goods
        # from two warehouses wait on each other although they touch
        # different shelves. Narrowing it means putting a location on the
        # layer — a model change with a valuation consequence — not
        # filtering this query.
        .with_for_update(of=[StockValuationLayer])
    )


def _drain_order(
    queue: list[StockValuationLayer], reverses_line_id: UUID | None
) -> list[StockValuationLayer]:
    """What is left of a product's prefetched layers, in the order a delivery drains them.

    The same order the statement gives: the layer of the line being reversed
    first, then the FIFO order the queue is already in. A layer with no line
    behind it sorts last, as ``NULL`` does there.
    """
    left = [layer for layer in queue if layer.remaining_qty > 0]
    if reverses_line_id is None:
        return left

    def rank(layer: StockValuationLayer) -> int:
        if layer.document_line_id is None:
            return 2
        return 0 if layer.document_line_id == reverses_line_id else 1

    return sorted(left, key=rank)


class ValuationService:
    """Service for AVCO inventory valuation."""

    @staticmethod
    async def record_receipt_by_id_async(
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal | None,
        document_line_id: UUID | None = None,
        currency: str | None = None,
        document_date: date | None = None,
        reverses_line_id: UUID | None = None,
        extra_unit_cost: Decimal = Decimal('0'),
    ) -> StockValuationLayer | None:
        """Async: record receipt by template_id (Public API helper).

        The template lookup is org-scoped: global templates
        (``organization_id IS NULL``) stay usable, anything else must
        belong to ``organization_id``. Without this the method happily
        valued another organization's template.
        """
        template = await _template_for_organization(
            db, organization_id, product_template_id
        )
        if template is None:
            return None
        return await ValuationService._record_receipt_async(
            db,
            template,
            quantity,
            unit_cost,
            organization_id,
            document_line_id,
            currency,
            document_date,
            reverses_line_id=reverses_line_id,
            extra_unit_cost=extra_unit_cost,
        )

    @staticmethod
    async def _reversed_outflow_cost(
        db: AsyncSession,
        template: ProductTemplate,
        organization_id: UUID,
        reverses_line_id: UUID,
    ) -> tuple[Decimal | None, str | None] | None:
        """What the outflow on *reverses_line_id* cost, per unit, in its currency.

        ``None`` when that line posted no outflow -- it is a receipt line, and
        the caller's stated price stands. ``(None, None)`` when it did but the
        books could not say what it cost: the goods are coming back, and a
        cost nobody knows is still not the sales price.
        """
        outflow = await db.scalar(
            select(StockValuationLayer)
            .where(
                StockValuationLayer.product_template_id == template.id,
                StockValuationLayer.organization_id == organization_id,
                StockValuationLayer.document_line_id == reverses_line_id,
                StockValuationLayer.direction == 'OUT',
            )
            .order_by(StockValuationLayer.created_at.asc())
            .limit(1)
        )
        if outflow is None:
            return None
        if not outflow.carries_a_cost or outflow.quantity <= 0:
            return None, None
        # The exact per-unit figure, off the value the layers actually gave
        # up; ``unit_cost`` on the row is that figure rounded.
        return outflow.total_value / outflow.quantity, outflow.currency

    @staticmethod
    async def _record_receipt_async(
        db: AsyncSession,
        template: ProductTemplate,
        quantity: Decimal,
        unit_cost: Decimal | None,
        organization_id: UUID,
        document_line_id: UUID | None = None,
        currency: str | None = None,
        document_date: date | None = None,
        reverses_line_id: UUID | None = None,
        extra_unit_cost: Decimal = Decimal('0'),
    ) -> StockValuationLayer | None:
        """Post a receipt layer. ``unit_cost=None`` means nobody named a price.

        A priceless inflow — a surplus off a count, a quantity raised by hand,
        a correction or a receipt line with no price — is valued at this
        organization's own current rate. Posting it at zero used to dilute
        the average and understate the assets on every surplus, and posting
        nothing at all used to break the equality between the shelf and the
        sum of the layers. When there is no rate to fall back on the layer is
        still posted, marked ``unknown``: the quantity is real even where the
        value is not known, and "unknown" is an answer a report can act on
        where "0.00" is not.

        *extra_unit_cost* is the line's share of the freight, duty and
        insurance the delivery arrived with, per unit. It rides on whatever
        cost the line has and decides nothing about where that cost came
        from: a priced line stays ``stated``, a priceless one stays
        ``average`` or ``unknown`` and carries the share on top. A return
        (*reverses_line_id*) takes no share; it comes back at what it cost.

        *reverses_line_id* names the outflow line whose goods are coming back
        -- a customer's return, a dispatch corrected downwards. Those goods
        left the books at what the layers they consumed cost, and they come
        back at that same figure: the price on the return line is what the
        customer paid, and a return is not a purchase at that price. Posting
        it as one put the margin on the shelf, once per return. Odoo prices
        a return from the original move and ERPNext from the original
        rate, for the same reason. A line that posted no outflow -- a receipt
        being corrected upwards -- is not a reversal, and its stated price
        stands.
        """
        if quantity <= 0:
            return None

        reversed_cost = (
            await ValuationService._reversed_outflow_cost(
                db, template, organization_id, reverses_line_id
            )
            if reverses_line_id is not None
            else None
        )
        if reversed_cost is not None:
            unit_cost, currency = reversed_cost

        if reversed_cost is not None and unit_cost is not None:
            # Valued at what the outflow it undoes took off the books: the
            # one formula, applied on the way back in as on the way out.
            cost_basis = CostBasis.FIFO
        elif unit_cost is not None:
            cost_basis = CostBasis.STATED
        else:
            # No stated price means no foreign amount to preserve either: the
            # fallback rate is the organization's own, kept in its own money,
            # whatever currency the document happened to be written in.
            currency = None
            unit_cost = await ValuationService._avco_rate_async(
                db, template, organization_id
            )
            if unit_cost is None:
                unit_cost = Decimal('0')
                cost_basis = CostBasis.UNKNOWN
            else:
                cost_basis = CostBasis.AVERAGE

        if extra_unit_cost and reversed_cost is None:
            unit_cost += extra_unit_cost

        # Resolved here rather than left NULL. A layer that does not say what
        # its cost is in leaves the next reader with the same guess this whole
        # column exists to remove — and one write path saying 'USD' while
        # another says nothing would read as two currencies.
        currency = currency or await _organization_currency(db, organization_id)

        # Rounded here, in the code, and rounded once. A cost that comes out
        # of an allocation — the freight spread over a delivery — carries as
        # many digits as the division produced, and the two columns hold
        # different widths. Left raw, Postgres rounded each on its own:
        # ``unit_cost`` to four decimals and ``total_value`` to two, off the
        # unrounded figure. The row then disagreed with its own arithmetic,
        # and a reconciliation reading both found a difference nothing in the
        # code had made.
        # The total first, off the exact cost, then the per-unit figure. A
        # freight allocation of 100.00 over three units is 33.333333... each:
        # rounding that first and multiplying loses a hundredth of the bill,
        # and the sum of the layers has to equal what was actually paid. It
        # is the same order the outflow side already keeps — the value is the
        # truth and the unit cost is the per-unit view of it.
        total_value = quantise(quantity * unit_cost)
        unit_cost = quantise(unit_cost, COST_PLACES)
        svl = StockValuationLayer(
            organization_id=organization_id,
            product_template_id=template.id,
            document_line_id=document_line_id,
            quantity=quantity,
            remaining_qty=quantity,
            unit_cost=unit_cost,
            total_value=total_value,
            direction='IN',
            currency=currency,
            cost_basis=cost_basis,
            document_date=document_date,
        )
        batch = current_batch(db)
        if batch is not None:
            # A layer the prefetched queue lacks: the next delivery reads again.
            batch.open_layers.pop((organization_id, template.id), None)
            # Written with the rest of the posting's rows. Nothing reads this
            # layer back before then: a reader of the layers asks for the
            # batch to be written first.
            svl.id = uuid.uuid4()
            batch.add(svl)
            return svl
        db.add(svl)
        await db.flush()

        return svl

    @staticmethod
    async def _avco_rate_async(
        db: AsyncSession, template: ProductTemplate, organization_id: UUID
    ) -> Decimal | None:
        """This organization's average cost for *template*, or None.

        Stock value is FIFO — layers leave first-in-first-out — and this
        rate is the average cost of the layers still on hand: an indicative
        figure that steps when a layer empties, not a true running average
        (AVCO). The ``avco`` name in identifiers is historical; this
        docstring is the formula's honest label.

        The only place this arithmetic lives. It used to be cached on
        ``ProductTemplate.current_valuation_rate`` and read from there, which
        cannot work: that column sits on a row a global template shares with
        every organization, so the figure belonged to whichever one wrote
        last. Two organizations stocking the same catalogue product at
        different prices valued each other's stock and read each other's
        purchase costs. The cache is gone; this is computed per read.

        A rate is one number, so it exists only while the layers behind it
        agree on a currency — the same answer ``cost_service`` gives a mixed
        batch of supplier prices — and while that currency is the
        organization's own. Every reader takes the bare number for the
        house's money, so stock bought in one foreign currency is refused
        exactly like a mixed batch: 100 × 40.10 złoty does not become a
        dollar rate because it is unanimous. Adding złoty to dollars would
        produce a number, and the number would be a fiction nobody could
        detect later.

        Only layers that carry a cost are averaged. Stock nobody priced sits
        on the books at 0.00 marked ``unknown``, and averaging it in handed
        the next priceless receipt that zero as the organization's own rate
        — the receipt then wrote it down as ``average``, a cost somebody
        knew. Where nothing on hand carries a cost there is no rate, and the
        receipt says ``unknown`` too.
        """
        result = await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template.id,
                StockValuationLayer.organization_id == organization_id,
                StockValuationLayer.remaining_qty > 0,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.carries_a_cost,
            )
        )
        layers = result.all()
        if not layers:
            return None

        house = await _organization_currency(db, organization_id)
        currencies = {layer.currency for layer in layers}
        if len(currencies) > 1 and None in currencies:
            # NULL means the organization's own currency — what every reader
            # assumed before the column existed, and what the backfill wrote
            # wherever it could. Resolve it only here, where it is the
            # difference between a real disagreement and a bookkeeping one.
            currencies = {house if c is None else c for c in currencies}
        if len(currencies) > 1:
            return None

        # Even a unanimous currency must be the house's own. The rate leaves
        # this function bare and every reader takes it for the organization's
        # money — the recipe cost labels it with the org currency, the
        # outgoing layer is written beside it — so a unanimous foreign
        # currency used to slip past the refusal above and come out as
        # dollars. A rate that lies about its currency is worth less than no
        # rate, and no rate is what a mixed batch already gets.
        (currency,) = currencies
        if currency is not None and currency != house:
            return None

        total_value = sum(
            (layer.remaining_qty * layer.unit_cost for layer in layers), Decimal('0')
        )
        total_qty = sum((layer.remaining_qty for layer in layers), Decimal('0'))
        if total_qty <= 0:
            return None
        return quantise(total_value / total_qty, COST_PLACES)

    @staticmethod
    async def lock_open_layers_async(
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: Iterable[UUID],
    ) -> None:
        """Lock and read the layers of these products once, for a posting's deliveries.

        Each delivery inside the posting then drains these objects instead of
        asking for its product's layers. A layer written for the product
        afterwards (a receipt line) drops the product's queue, and a rollback
        drops them all, so a delivery never drains a queue that is not the
        database's. Outside a posting nothing is read.
        """
        batch = current_batch(db)
        if batch is None:
            return
        wanted = {
            t
            for t in product_template_ids
            if (organization_id, t) not in batch.open_layers
        }
        if not wanted:
            return
        queues: dict[UUID, list[StockValuationLayer]] = {t: [] for t in wanted}
        for layer in (await db.scalars(_open_layers(organization_id, wanted))).all():
            queues[layer.product_template_id].append(layer)
        for template_id, queue in queues.items():
            batch.open_layers[(organization_id, template_id)] = queue

    @staticmethod
    async def post_delivery_by_id_async(
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        document_line_id: UUID | None = None,
        reason: str | None = None,
        item_id: UUID | None = None,
        reverses_line_id: UUID | None = None,
    ) -> DeliveryPosting:
        """Async: record delivery by template_id (Public API helper).

        The template lookup is org-scoped exactly like the receipt path;
        a foreign template returns no consumed layers and never touches
        its owner's stock.

        *reason* is why the stock left, where the caller knows — a use, a
        disposal. It travels onto the outgoing layer so the consumption and
        waste reports can tell those apart. A dispatch against a document
        passes nothing: goods leaving for a customer are neither.
        """
        template = await _template_for_organization(
            db, organization_id, product_template_id
        )
        if template is None:
            return DeliveryPosting([], None)
        return await ValuationService._post_delivery_async(
            db,
            template,
            quantity,
            organization_id,
            document_line_id,
            reason=reason,
            item_id=item_id,
            reverses_line_id=reverses_line_id,
        )

    @staticmethod
    async def get_current_valuation_rate_async(
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
    ) -> Decimal | None:
        """Return *organization_id*'s AVCO rate for a template, or None.

        Cheap read used by recipes picking undo to fall back to the
        current rate when ``consumed_valuation_rate`` is not snapshotted
        on legacy PickingSessionItem rows. Returns ``None`` when the
        template is missing or this organization has no layers for it.

        Computed from the organization's own layers rather than read off
        ``template.current_valuation_rate``. That column lives on the template
        row, and a global template — the whole default catalogue — is shared by
        every organization, so the figure there belonged to whichever one wrote
        last: an organization could read a competitor's purchase cost off a
        catalogue product, and value its own stock with it. The org filter that
        used to be missing from this method was added once already; it does not
        help while the number itself is shared.

        ``None`` also when the layers cannot back a rate in the organization's
        own money — they mix currencies, or all of the stock was bought in one
        foreign one (see :meth:`_avco_rate_async`).
        """
        template = await db.scalar(
            select(ProductTemplate).where(
                ProductTemplate.id == product_template_id,
                (ProductTemplate.organization_id == organization_id)
                | (ProductTemplate.organization_id.is_(None)),
            )
        )
        if template is None:
            return None
        return await ValuationService._avco_rate_async(db, template, organization_id)

    @staticmethod
    async def get_valuation_rates_batch_async(
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: list[UUID],
    ) -> dict[UUID, Decimal | None]:
        """Return ``{template_id: this organization's AVCO rate}``.

        Batch counterpart of :meth:`get_current_valuation_rate_async`:
        one query instead of N for multi-level BoM cost rollups.
        Templates this organization has no layers for map to ``None``.
        Duplicate ids are de-duplicated.

        Aggregated over the organization's layers rather than read off
        ``ProductTemplate.current_valuation_rate``: that column is one number
        on a row a global template shares with every organization, so reading
        it here handed a BoM rollup somebody else's purchase cost — and which
        somebody else depended on who had last taken a delivery.

        The currency rule is the one :meth:`_avco_rate_async` applies row by
        row: a rate is one number, so it exists only while the layers behind it
        agree on a currency, and only while that currency is the house's own —
        every reader takes the bare rate for the organization's money, so
        stock bought in one foreign currency is refused like a mixed batch.
        ``NULL`` means the organization's own, so it is
        resolved to the house currency before the comparison rather than
        counted as a disagreement. And only layers that carry a cost are
        averaged, for the reason :meth:`_avco_rate_async` gives: a bill of
        materials costed off stock nobody priced read its 0.00 as a price.
        """
        if not product_template_ids:
            return {}

        house = await _organization_currency(db, organization_id)
        currency = func.coalesce(StockValuationLayer.currency, house)
        rows = (
            await db.execute(
                select(
                    StockValuationLayer.product_template_id,
                    func.sum(
                        StockValuationLayer.remaining_qty
                        * StockValuationLayer.unit_cost
                    ).label('total_value'),
                    func.sum(StockValuationLayer.remaining_qty).label('total_qty'),
                    func.count(distinct(currency)).label('currencies'),
                    # The single currency behind the rate when ``currencies``
                    # is 1 — NULL where the layers never said, which an
                    # organization with no currency of its own reads as
                    # itself.
                    func.min(currency).label('currency'),
                )
                .where(
                    StockValuationLayer.product_template_id.in_(
                        set(product_template_ids)
                    ),
                    StockValuationLayer.organization_id == organization_id,
                    StockValuationLayer.remaining_qty > 0,
                    StockValuationLayer.direction == 'IN',
                    StockValuationLayer.carries_a_cost,
                )
                .group_by(StockValuationLayer.product_template_id)
            )
        ).all()

        rates: dict[UUID, Decimal | None] = dict.fromkeys(
            set(product_template_ids), None
        )
        for row in rows:
            if row.currencies > 1 or not row.total_qty or row.total_qty <= 0:
                continue
            # The same house-currency rule :meth:`_avco_rate_async` applies
            # row by row: the rate is handed out only in the organization's
            # own money, so a unanimous foreign currency is refused like a
            # mixed batch.
            if row.currency is not None and row.currency != house:
                continue
            rates[row.product_template_id] = quantise(
                Decimal(str(row.total_value)) / Decimal(str(row.total_qty)),
                COST_PLACES,
            )
        return rates

    @staticmethod
    async def _post_delivery_async(
        db: AsyncSession,
        template: ProductTemplate,
        quantity: Decimal,
        organization_id: UUID,
        document_line_id: UUID | None = None,
        reason: str | None = None,
        item_id: UUID | None = None,
        reverses_line_id: UUID | None = None,
    ) -> DeliveryPosting:
        """Take *quantity* off the receipt layers and post what it was worth.

        ``direction`` has been on this table since it was created and only
        ever held ``'IN'``. An outflow drained the receipt layers, recomputed
        the average, and left no record of its own value — so the reports
        that exist to say what was consumed and what was thrown away had no
        source, and read the figure out of a JSON blob nothing writes.

        The outgoing layer is posted at what the layers it consumes actually
        cost, and is never recomputed: a report about March has to say the
        same thing in December.

        *reverses_line_id* names the receipt line whose goods are going back
        — a correction of a delivery, a return to the supplier. Those goods
        arrived on one identifiable layer at one identifiable price, so that
        layer is drained first and the rest of the queue only covers what it
        can no longer cover itself. Draining strict FIFO instead took the
        cheapest delivery in the warehouse off the books and left the
        expensive one that is actually being sent back standing on them.

        It used to be posted at the average of the layers still on hand, read
        before the drain. The drain was FIFO, so one move carried two
        formulas: ten units bought at 1.00 and ten at 3.00, then ten
        delivered, took a 10.00 layer off the shelf and wrote a 20.00 row.
        The books then held 40.00 bought, 20.00 gone and 30.00 standing, and
        the ten that came from nowhere made stock value and consumption
        impossible to reconcile against purchases. IAS 2 asks for one formula
        applied consistently; the balance sheet side was already FIFO, so this
        is the number that moves.
        """
        if quantity <= 0:
            return DeliveryPosting([], None)

        remaining_to_deliver = quantity
        consumed_layers = []
        # What the goods cost where they were bought, accumulated as the
        # layers are drained. Full precision: it is divided by the quantity
        # below, and rounding the parts before summing them is how a total
        # stops matching its own lines.
        consumed_value = Decimal('0')
        # The currencies behind that sum. Layers are drained by age, not by
        # what they were bought in, so a template with a foreign receipt in
        # its history can hand this loop two currencies that do not add.
        consumed_currencies: set[str | None] = set()
        # Whether every layer drained knew what its stock cost. A layer that
        # did not gives up 0.00, and 0.00 is not what the goods cost.
        consumed_only_costs = True

        batch = current_batch(db)
        queue = (
            batch.open_layers.get((organization_id, template.id))
            if batch is not None
            else None
        )
        if queue is not None:
            # Read and locked ahead of the posting (``lock_open_layers_async``):
            # the lines before this one have drained what they took from the
            # objects, and the queue is in FIFO order already.
            layers = _drain_order(queue, reverses_line_id)
        else:
            layers = list(
                (
                    await db.scalars(
                        _open_layers(organization_id, [template.id], reverses_line_id)
                    )
                ).all()
            )

        for layer in layers:
            if remaining_to_deliver <= 0:
                break

            taken = min(layer.remaining_qty, remaining_to_deliver)
            consumed_value += taken * layer.unit_cost
            consumed_currencies.add(layer.currency)
            consumed_only_costs = consumed_only_costs and layer.carries_a_cost
            layer.remaining_qty = layer.remaining_qty - taken
            remaining_to_deliver = remaining_to_deliver - taken
            consumed_layers.append(layer)

        if batch is None:
            # Inside a posting the changed layers are written with the next
            # statement that reads, or with the end of the posting, as one
            # set of updates rather than one after each line.
            await db.flush()

        if remaining_to_deliver > 0:
            # The layers did not cover the move. This used to end here in
            # silence — no exception, no log line — and the average then fell
            # to None while stock still stood on the shelf, quietly pushing
            # recipe costs onto the supplier price instead. Refusing the move
            # is not an option: the goods have already left, and legacy stock
            # that predates the cost history is a real and blameless case.
            # So it is said out loud, and the layer below records it as
            # unknown rather than as nothing.
            logger.warning(
                'Outflow of %s for template %s in organization %s is not '
                'covered by the cost history: %s without a layer behind it',
                quantity,
                template.id,
                organization_id,
                remaining_to_deliver,
            )

        # ``remaining_qty`` is zero because an outgoing layer is not stock
        # anybody can draw on later, and every rate query filters
        # ``direction == 'IN'`` — so this row cannot reach the average.
        #
        # It is posted even when the layers held nothing. Skipping it lost the
        # move from the ledger entirely: the stock left the shelf and the books
        # held nothing about it, which is the same silence in a new place.
        #
        # ``total_value`` is what the layers actually gave up, so the equation
        # holds by construction: what the books lose is exactly what the shelf
        # loses.
        #
        # Two cases where it is not the whole cost, and both say so rather
        # than putting a confident figure over a short one:
        #
        # * the layers did not cover the move — the value is exact for the
        #   part they covered and silent about the rest;
        # * some of the layers consumed carry no cost — stock nobody priced,
        #   the opening balance of a shelf older than the ledger. They cover
        #   the quantity and give up 0.00, and writing that down as ``fifo``
        #   told every report the goods had cost nothing;
        # * the layers consumed do not agree on a currency, or agree on one
        #   that is not the organization's. Amounts in different money do not
        #   add, and the rate this used to be posted at refused a mixed batch
        #   for the same reason. There is no sum to write, so there is none.
        house = await _organization_currency(db, organization_id)
        priced_in_house = {house if c is None else c for c in consumed_currencies} <= {
            house
        }
        if not priced_in_house:
            consumed_value = Decimal('0')
        covered = remaining_to_deliver <= 0 and consumed_only_costs and priced_in_house
        outgoing = StockValuationLayer(
            organization_id=organization_id,
            product_template_id=template.id,
            document_line_id=document_line_id,
            quantity=quantity,
            remaining_qty=Decimal('0'),
            unit_cost=quantise(consumed_value / quantity, COST_PLACES),
            total_value=quantise(consumed_value),
            direction='OUT',
            reason=reason,
            item_id=item_id,
            # The house's own sign, and it cannot be mislabelled: a cost
            # is only summed above while every layer behind it is in this
            # currency. Where it is not, the amount is zero and
            # ``cost_basis`` says the cost is unknown.
            currency=house,
            cost_basis=CostBasis.FIFO if covered else CostBasis.UNKNOWN,
        )
        batch = current_batch(db)
        if batch is not None:
            # Written with the rest of the posting's rows, at its end: it is
            # added unread, so no statement calls for it early. Nothing in a
            # posting reads an outgoing layer; one that came to would have to
            # be added without ``unread``.
            outgoing.id = uuid.uuid4()
            batch.add(outgoing, unread=True)
        else:
            db.add(outgoing)
            await db.flush()

        return DeliveryPosting(consumed_layers, consumed_value if covered else None)
