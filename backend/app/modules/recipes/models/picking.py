"""PickingSession and PickingSessionItem models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from .recipe import Recipe, RecipeIngredient


class PickingSession(Base):
    __tablename__ = 'picking_sessions'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('recipes.id', ondelete='CASCADE')
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    # The meal-plan entry whose Cook Now started this session, so the plan
    # marks the card that was cooked and not a sibling of the same recipe.
    # NULL for a session started from the recipe page, which the plan still
    # attributes by the day it finished.
    meal_plan_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('meal_plan_entries.id', ondelete='SET NULL'), index=True
    )
    servings: Mapped[int] = mapped_column(Integer, default=1)
    # How much of the recipe this session cooks, as a multiplier (1.4 of a
    # two-serving recipe). NULL means a portioned session: the multiplier
    # is derived from ``servings`` the way it always was, so every session
    # before this column stays readable without a backfill. A stated scale
    # wins over ``servings`` on every read.
    scale: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default='active'
    )  # active | completed | cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)  # 1-5 stars

    recipe: Mapped[Recipe] = relationship('Recipe', lazy='selectin')
    items: Mapped[list[PickingSessionItem]] = relationship(
        'PickingSessionItem',
        back_populates='session',
        cascade='all, delete-orphan',
        lazy='selectin',
    )


class PickingSessionItem(Base):
    __tablename__ = 'picking_session_items'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('picking_sessions.id', ondelete='CASCADE'),
        index=True,
    )
    # Nullable on purpose: an ingredient dropped from the recipe must not take
    # the consumption record down with it. The row detaches and keeps reading
    # through the snapshot columns below.
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('recipe_ingredients.id', ondelete='SET NULL'),
    )
    # Snapshot of what the recipe asked for at session start — the only thing
    # left to read once the ingredient itself is gone.
    ingredient_name: Mapped[str | None] = mapped_column(String(255))
    required_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    required_uom_symbol: Mapped[str | None] = mapped_column(String(10))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL')
    )
    quantity_consumed: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    # Breakdown of multi-item partial picks for correct restore on undo/cancel:
    # [{"item_id": "<uuid>", "quantity": "<decimal>"}]
    picked_items: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    # AVCO rate at consume time — snapshot so undo restores at the correct cost
    consumed_valuation_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String(20), default='pending'
    )  # pending | picked | skipped

    session: Mapped[PickingSession] = relationship(
        'PickingSession', back_populates='items'
    )
    ingredient: Mapped[RecipeIngredient | None] = relationship('RecipeIngredient')
