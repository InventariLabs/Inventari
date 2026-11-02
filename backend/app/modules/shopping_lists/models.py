import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# The quantity columns' shape lives with the validators that police it —
# the schemas refuse the same ceiling this column holds.
from app.schemas.validators import QUANTITY_MAX_DIGITS, QUANTITY_SCALE


class ShoppingListStatus(StrEnum):
    """explicit state machine for shopping lists."""

    ACTIVE = 'active'  # accepting new items + purchases
    COMPLETED = 'completed'  # all items purchased; frozen but readable
    ARCHIVED = 'archived'  # no edits allowed; read-only archive


class ShoppingList(Base):
    """
    Shopping list for a organization.
    Can have multiple active lists (e.g., "Biedronka", "Tesco online").
    """

    __tablename__ = 'shopping_lists'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE')
    )

    name: Mapped[str] = mapped_column(
        String(255), default='Shopping List'
    )  # "Grocery store", "Online order"

    # The state machine and the only place a list's state lives.
    status: Mapped[str] = mapped_column(
        String(20), default=ShoppingListStatus.ACTIVE.value, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization: Mapped['Organization'] = relationship()  # type: ignore[name-defined]
    creator: Mapped['User'] = relationship(foreign_keys=[created_by])  # type: ignore[name-defined]
    items: Mapped[list['ShoppingListItem']] = relationship(
        'app.modules.shopping_lists.models.ShoppingListItem',
        back_populates='shopping_list',
        cascade='all, delete-orphan',
    )


class ShoppingListItem(Base):
    """
    Single item on a shopping list.
    """

    __tablename__ = 'shopping_list_items'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    shopping_list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('shopping_lists.id', ondelete='CASCADE')
    )

    # Link to product (optional - if auto-suggestion)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL')
    )

    # Product template link (optional — enables grouping into purchase orders)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='SET NULL')
    )

    # Category (optional - for filtering in store)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('categories.id'))

    # Item data
    name: Mapped[str] = mapped_column(String(255))  # "Milk 3.2%", "Vanilla ice cream"
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_MAX_DIGITS, QUANTITY_SCALE), default=1
    )
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(
        Text
    )  # "Best from local store", "If on promotion"

    # Structured note parts for lines a service composed (meal-plan shopping).
    # The plain `notes` keeps the composed-at-generation text as the fallback
    # for consumers that cannot re-render; the interface prefers this and
    # composes the sentence in the reader's language, translating the unit
    # symbols through its own catalog.
    note_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Estimated price (optional - for budgeting)
    estimated_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # Status
    is_purchased: Mapped[bool] = mapped_column(default=False, index=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchased_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))

    # Source (suggestion vs. manual)
    source: Mapped[str] = mapped_column(
        String(50), default='manual'
    )  # 'manual', 'auto_low_stock', 'auto_consumption', 'auto_expiring'

    # Priority (optional)
    priority: Mapped[int] = mapped_column(
        Integer, default=0
    )  # 0=normal, 1=high, 2=urgent

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    shopping_list: Mapped['ShoppingList'] = relationship(
        'app.modules.shopping_lists.models.ShoppingList', back_populates='items'
    )
    item: Mapped['Item'] = relationship()  # type: ignore[name-defined]
    category: Mapped['Category'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    purchaser: Mapped['User | None'] = relationship(foreign_keys=[purchased_by])  # type: ignore[name-defined]
    uom = relationship('Uom', lazy='joined', foreign_keys=[uom_id])


class ShoppingListHistory(Base):
    """snapshot of purchased items preserved on list deletion.

    Keeps the "I spent X on groceries in March" history intact even when
    the original ShoppingList and its items are removed.
    """

    __tablename__ = 'shopping_list_history'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    original_list_id: Mapped[uuid.UUID] = mapped_column(index=True)
    original_list_name: Mapped[str] = mapped_column(String(255))
    item_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_MAX_DIGITS, QUANTITY_SCALE), default=1
    )
    estimated_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchased_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
