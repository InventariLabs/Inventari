import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    and_,
    case,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.contracts._stock_dtos import LotStatus
from app.database import Base

__all__ = ['LotStatus', 'StockLot', 'effective_status_expression']

if TYPE_CHECKING:
    from app.models.product_template import ProductTemplate


class StockLot(Base):
    """
    Production lot or serial number tracking.

    A lot represents a batch of products sharing the same origin.
    When ``is_serial`` is True the lot represents a single unique item
    (serial-number tracking).

    ``organization_id`` is always set — every lot belongs to a tenant.
    """

    __tablename__ = 'stock_lots'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    is_serial: Mapped[bool] = mapped_column(default=False)

    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    production_date: Mapped[date | None] = mapped_column(Date)
    use_by_date: Mapped[date | None] = mapped_column(Date)

    removal_strategy: Mapped[str] = mapped_column(String(10), default='FIFO')

    status: Mapped[str] = mapped_column(String(20), default=LotStatus.ACTIVE)

    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    product_template: Mapped['ProductTemplate'] = relationship()

    @property
    def effective_status(self) -> str:
        """The state the batch is really in, date included.

        ``status`` is what somebody decided; the expiry date is a fact that
        needs no deciding, and nothing in the system ever turned it into
        one — ``LotStatus.EXPIRED`` existed and no code path wrote it, so
        the tab was empty and the picking gate, which reads the status, let
        a month-old batch through.

        A decision outranks the date: a batch withdrawn on a supplier's
        notice stays recalled after its date passes, because "recalled"
        answers a question "expired" does not. The SQL twin of this rule is
        :func:`effective_status_expression` — change both or neither.
        """
        if self.status != LotStatus.ACTIVE:
            return self.status
        dates = [d for d in (self.use_by_date, self.expiry_date) if d is not None]
        if dates and min(dates) < datetime.now(UTC).date():
            return LotStatus.EXPIRED
        return self.status

    @property
    def status_reason(self) -> str | None:
        """Why the batch is in the state it is in, if anybody said.

        Read off the last entry of ``meta_data['status_history']``, and only
        when that entry is about the state the batch is actually in: the
        module paths (``quarantine_lot_async`` / ``release_lot_async``)
        change the status without appending, so the newest entry can describe
        a state the batch has since left. A stale explanation beside a
        current status is worse than none.
        """
        history = (self.meta_data or {}).get('status_history') or []
        if not history:
            return None
        last = history[-1]
        if not isinstance(last, dict) or last.get('status') != self.status:
            return None
        reason = last.get('reason')
        return reason if isinstance(reason, str) else None

    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            'name',
            name='uq_lot_org_product_name',
        ),
        Index('ix_lot_org_expiry', 'organization_id', 'expiry_date'),
    )


def effective_status_expression():
    """SQL twin of :attr:`StockLot.effective_status`.

    Written as an expression rather than computed per row so that the batch
    list can both filter and count on it — a status the page can show but
    not narrow to is the empty tab all over again.
    """
    earliest = func.least(
        func.coalesce(StockLot.use_by_date, StockLot.expiry_date),
        func.coalesce(StockLot.expiry_date, StockLot.use_by_date),
    )
    return case(
        (
            and_(
                StockLot.status == LotStatus.ACTIVE,
                earliest.is_not(None),
                earliest < func.current_date(),
            ),
            LotStatus.EXPIRED.value,
        ),
        else_=StockLot.status,
    )
