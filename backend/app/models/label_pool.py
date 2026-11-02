import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base


class LabelPool(Base):
    __tablename__ = 'label_pool'
    # short_code is unique within an organization (not globally) so two
    # tenants may reuse the same code (e.g. "A-0042").
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'short_code', name='uq_label_pool_org_short_code'
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    short_code: Mapped[str] = mapped_column(String(100))
    is_assigned: Mapped[bool] = mapped_column(default=False, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            'items.id',
            ondelete='SET NULL',
            use_alter=True,
            name='fk_label_pool_item_id',
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE')
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))

    # New fields
    label_type: Mapped[str] = mapped_column(
        String(50), default='GENERIC'
    )  # GENERIC, STORAGE, CATEGORY
    description: Mapped[str | None] = mapped_column(String(255))
    target_storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL')
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    target_location_id: Mapped[uuid.UUID | None] = synonym('target_storage_location_id')
    context_tag: Mapped[str | None] = mapped_column(String(50), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_count: Mapped[int] = mapped_column(Integer, default=0)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped['Organization'] = relationship()  # type: ignore[name-defined]
    creator: Mapped['User'] = relationship()  # type: ignore[name-defined]
    target_storage: Mapped['StorageLocation'] = relationship()  # type: ignore[name-defined]
    assigned_item: Mapped['Item'] = relationship(foreign_keys=[item_id])  # type: ignore[name-defined]

    if TYPE_CHECKING:
        # Non-DB enrichment attributes (populated at query time, not persisted)
        is_item_deleted: bool | None
        assigned_item_name: str | None
        assigned_item_quantity: object
        assigned_item_unit: str | None
        # The context tag of the category the assigned item is filed under —
        # what the label points at, which is not always what it was printed for.
        assigned_item_context_tag: str | None
        assigned_item_expiry: object
