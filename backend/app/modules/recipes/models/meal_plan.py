"""MealPlan, MealPlanEntry, and ShoppingExclusion models."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

from .recipe import MealSlot

if TYPE_CHECKING:
    from app.models import ProductTemplate

    from .recipe import Recipe


class MealPlan(Base):
    __tablename__ = 'meal_plans'
    __table_args__ = (
        Index('ix_meal_plans_org_start', 'organization_id', 'start_date'),
        Index('ix_meal_plans_org_end', 'organization_id', 'end_date'),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    enabled_slots: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: ['LUNCH']
    )
    # No column default: NULL is the meaningful value here — it means "this
    # plan states no default", and each entry then follows its own recipe.
    # A column default of 2 also overrode an explicitly passed None, so the
    # answer could not be given at all.
    default_servings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shopping_list_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # The meals the shopping list was last generated from, as
    # ``[recipe_id, effective servings]`` pairs; the plan screen compares the
    # meals it holds now against them (``meals_not_on_the_list``). NULL for a
    # plan that never had a list, or had one before this was kept — which the
    # screen treats as a list it cannot vouch for.
    listed_meals: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id'), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    entries: Mapped[list[MealPlanEntry]] = relationship(
        'MealPlanEntry',
        back_populates='meal_plan',
        cascade='all, delete-orphan',
        order_by='MealPlanEntry.date, MealPlanEntry.order',
    )


class MealPlanEntry(Base):
    __tablename__ = 'meal_plan_entries'
    __table_args__ = (
        UniqueConstraint(
            'meal_plan_id',
            'date',
            'slot',
            'order',
            name='uq_meal_plan_entries_plan_date_slot_order',
        ),
        Index('ix_meal_plan_entries_plan_date', 'meal_plan_id', 'date'),
        Index('ix_meal_plan_entries_recipe', 'recipe_id'),
        Index('ix_meal_plan_entries_date', 'date'),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('meal_plans.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[MealSlot] = mapped_column(
        SAEnum(
            MealSlot,
            native_enum=False,
            length=20,
            create_constraint=True,
            name='ck_meal_plan_entries_slot',
        ),
        nullable=False,
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('recipes.id', ondelete='CASCADE'),
        nullable=False,
    )
    servings: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meal_plan: Mapped[MealPlan] = relationship('MealPlan', back_populates='entries')
    recipe: Mapped[Recipe] = relationship('Recipe')


class ShoppingExclusion(Base):
    __tablename__ = 'shopping_exclusions'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'name_normalized',
            name='uq_shopping_exclusions_org_name',
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    template: Mapped[ProductTemplate | None] = relationship()
