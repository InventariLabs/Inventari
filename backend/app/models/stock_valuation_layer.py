"""Stock Valuation Layer model for AVCO costing."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    literal_column,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

#: The date a cost layer is *about*, written as SQL so an index can hold it.
#:
#: ``document_date`` is the day a receipt belongs to; a layer with no document
#: behind it falls back to the day its row was written. Casting a
#: ``timestamptz`` to a date reads the session's ``TimeZone`` and is therefore
#: only STABLE, which no index expression may be — pinning the conversion to
#: UTC, the zone the ledger is written and read in, is what makes the
#: expression immutable and the index below possible.
LAYER_DATED_AT_SQL = "coalesce(document_date, (created_at AT TIME ZONE 'UTC')::date)"


def layer_dated_at() -> ColumnElement[Any]:
    """The date a cost layer is about, as the index above stores it.

    One definition for both sides: the expressions of a query and of an index
    have to be the same tree for the planner to use one for the other, so the
    readers build theirs from this text rather than typing it again.
    """
    return literal_column(LAYER_DATED_AT_SQL)


class CostBasis:
    """Where a layer's ``unit_cost`` came from.

    An inflow with no price used to be posted at 0.00 by one caller and not
    posted at all by another. Both answers lie in the same direction: the
    first dilutes the average and understates the assets, the second breaks
    the equality between what is on the shelf and what the layers add up to.
    A cost that nobody stated is neither zero nor absent — it is unknown, and
    the ledger now says which of the three it is.
    """

    #: Somebody named the price — a supplier invoice, a priced document line.
    STATED = 'stated'
    #: Nobody named it, so the organization's own current rate was used.
    AVERAGE = 'average'
    #: Nobody named it and there was no rate to fall back on. The quantity is
    #: real; the value is not known and must not be read as zero. An outflow
    #: the layers could not fully cover is marked this way too, and so is one
    #: that drained layers marked this way: what it took off the books is
    #: exact, but it is not the whole cost of what left. Whether a layer is
    #: one of these is :attr:`StockValuationLayer.carries_a_cost`.
    UNKNOWN = 'unknown'
    #: An outflow, valued at what the layers it actually consumed cost.
    #: One formula, applied consistently, as IAS 2 asks. Outgoing rows written
    #: before this existed were valued at the average of the layers on hand,
    #: yet they are marked ``stated``: the migration that added the column
    #: gave every row already there that one value, inflows and outflows
    #: alike, and could not tell them apart afterwards.
    FIFO = 'fifo'


class StockValuationLayer(Base):
    """
    Tracks individual inventory receipt layers for AVCO valuation.

    Each time inventory is received, a new SVL record is created with:
    - quantity received
    - remaining_qty (decreases as inventory is consumed)
    - unit_cost at time of receipt

    AVCO is calculated as: total_value / total_quantity across all layers.
    """

    __tablename__ = 'stock_valuation_layers'
    __table_args__ = (
        # A layer holds what is left of a receipt. Less than nothing is not a
        # state it can be in, and the table used to have no opinion — so a
        # lost update while two outflows drained it at once left damage that
        # read like data.
        CheckConstraint('remaining_qty >= 0', name='ck_svl_remaining_not_negative'),
        # The drain reads one organization's open layers of one product
        # (``remaining_qty > 0``) and nothing else. A template id alone is
        # not unique across tenants: product templates are shared, so the
        # ledger of every organization that ever bought the goods sits under
        # the same id. Ordered by template alone the index handed the scan
        # other organizations' rows to be filtered afterwards — rows nobody
        # asked for, read one by one on the path that runs on every receipt
        # and issue. The organization comes first so the read is of the one
        # tenant that asked.
        #
        # ``ix_svl_org_template`` is now a prefix of this index and the
        # narrower one is left in place on purpose: dropping it is a
        # separate decision about a table written on every movement, not
        # something this index gets to make.
        Index(
            'ix_svl_template_remaining',
            'organization_id',
            'product_template_id',
            'remaining_qty',
        ),
        Index('ix_svl_org_template', 'organization_id', 'product_template_id'),
        # The shape the consumption and waste reports read: one organization's
        # outgoing layers, split by reason.
        Index('ix_svl_org_direction_reason', 'organization_id', 'direction', 'reason'),
        # The valuation of a day cuts on the date a layer is about and orders
        # by that same date, in three statements — the receipts it replays,
        # the count of what a foreign currency dropped, and the outflow total.
        # None of them can be served by an index on ``document_date`` alone:
        # a layer with no document behind it is dated by its write time, so
        # the cut and the sort both run over the coalesce. Without this index
        # the database reads the organization's whole cost history and sorts
        # it in memory on every call, and the report is asked for a day at a
        # time. ``id`` is a key column rather than an INCLUDE one because the
        # ordering ends on it: a covering column does not participate in the
        # sort, so the plan would still need a Sort node above it.
        # ``created_at`` is the tiebreaker the ordering names second.
        Index(
            'ix_svl_org_direction_dated_at',
            'organization_id',
            'direction',
            text(LAYER_DATED_AT_SQL),
            'created_at',
            'id',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )

    document_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('document_lines.id', ondelete='SET NULL'),
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    #: The receipt's business date, stated by the document — its scheduled
    #: date. FIFO consumes in business-date order, not in the order rows
    #: happened to be written; a booking typed late must not push the goods
    #: it describes to the back of the queue. NULL on layers with no
    #: document behind them (manual edits, stock-take surpluses): those fall
    #: back to their write time when the order is decided.
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: What currency ``unit_cost`` is in — and nothing else.
    #:
    #: Recorded rather than assumed. Every reader used to take this number for
    #: the organization's own currency, so a receipt priced in the supplier's
    #: wrote a foreign amount into the cost history where nothing could see it
    #: for what it was. NULL means the organization's currency, which is what
    #: the assumption said all along.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    direction: Mapped[str] = mapped_column(String(10), nullable=False)

    #: Where ``unit_cost`` came from — see :class:`CostBasis`.
    #:
    #: Rows written before this column existed are marked ``stated``, because
    #: that is what the code claimed at the time. History from then cannot
    #: tell a receipt genuinely priced at zero from one where nobody said a
    #: price at all; that indistinguishability is the defect this closes.
    cost_basis: Mapped[str] = mapped_column(
        String(10), nullable=False, default=CostBasis.STATED
    )

    #: Why the stock left, on an ``OUT`` layer. NULL on receipts and on
    #: outflows that are neither a use nor a disposal — a dispatch against a
    #: document is stock going where it was sold to, not stock consumed.
    #:
    #: The waste and consumption reports are entirely about telling a use
    #: from a disposal, and ``direction`` cannot say which. Odoo attributes
    #: the same thing by the move's destination location; here the move to a
    #: virtual location happens after the quantity change and only when the
    #: record reaches zero, so the reason has to travel with the layer.
    reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    #: The record the stock left, on an ``OUT`` layer written by an item path.
    #:
    #: ``document_line_id`` has always named the source for document flows;
    #: this is its counterpart for the flows that start from a record on a
    #: shelf. Without it the value of one product template would have to be
    #: split across however many records share it, and a report that
    #: apportions is a report that estimates.
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL'),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    @hybrid_property
    def carries_a_cost(self) -> bool:
        """Whether ``unit_cost`` is a cost anybody knows.

        An ``unknown`` layer holds 0.00 where nobody named a price and there
        was no rate to borrow. The quantity on it is real; the figure is not a
        cost. Readers used to decide this one by one, and they disagreed: the
        footer left such layers out of its rate, while the rate a priceless
        receipt borrows averaged them in — so the second priceless arrival of
        a product nobody priced borrowed 0.00 from the first and wrote it down
        as the organization's ``average``, a known cost of zero for goods
        whose cost was never known.

        So it is asked here, once, in SQL and on a loaded row alike: by every
        rate, by the drain pricing what left, and by the reports asking
        whether an outflow was priced.
        """
        return self.cost_basis != CostBasis.UNKNOWN

    organization: Mapped['Organization'] = relationship()  # type: ignore[name-defined]
    product_template: Mapped['ProductTemplate'] = relationship()  # type: ignore[name-defined]
    document_line: Mapped['DocumentLine | None'] = relationship()  # type: ignore[name-defined]

    def __repr__(self):
        return (
            f'<StockValuationLayer(template={self.product_template_id}, '
            f'qty={self.quantity}, remaining={self.remaining_qty}, '
            f'cost={self.unit_cost})>'
        )
