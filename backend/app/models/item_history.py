import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.contracts import ItemAction
from app.database import Base

__all__ = ['ItemAction', 'ItemHistory', 'CONSUMPTION_ACTIONS', 'DISPOSAL_ACTIONS']


# Canonical action groupings for queries: what the reports count as a use and
# what they count as a disposal. The names outlive any one query so a report
# cannot drift into counting half the story.
CONSUMPTION_ACTIONS: tuple[str, ...] = (ItemAction.USED.value,)
DISPOSAL_ACTIONS: tuple[str, ...] = (ItemAction.DISPOSED.value,)


class ItemHistory(Base):
    """
    Item change history:
    - Created
    - Updated
    - Moved
    - Used/Disposed/Deleted
    """

    __tablename__ = 'item_history'
    __table_args__ = (
        Index('ix_item_history_item_created', 'item_id', 'created_at'),
        # The reports' window: one organization, one kind of event, since a
        # date — what consumption, waste and the valuation check all ask.
        Index(
            'ix_item_history_org_action_created',
            'organization_id',
            'action',
            'created_at',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE')
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), index=True
    )
    action: Mapped[str] = mapped_column(String(50))  # ItemAction Enum values
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # change details
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('documents.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    organization: Mapped['Organization'] = relationship()  # type: ignore[name-defined]
    item: Mapped['Item'] = relationship(back_populates='history')  # type: ignore[name-defined]
    user: Mapped['User | None'] = relationship(backref='activity_history')  # type: ignore[name-defined]
