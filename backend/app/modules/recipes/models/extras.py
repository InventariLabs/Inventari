"""Recipe tag config, ingredient nutrition defaults, and unit conversions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecipeTagConfig(Base):
    """Per-organisation tag configuration — stores display color per tag name."""

    __tablename__ = 'recipe_tag_configs'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'name', name='uq_recipe_tag_configs_org_name'
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(20))  # e.g. '#FF5733'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class IngredientNutritionDefault(Base):
    """Per-language ingredient nutrition defaults.

    organization_id = NULL  -> system defaults (seeded, read-only for users)
    organization_id = <uuid> -> org override (user-managed)

    Lookup order: org override wins over system default.

    Not the same thing as ``item.meta_data['nutrition']``, and deliberately not
    connected to it. This table answers "roughly what is in wheat flour",
    keyed by an ingredient *name*, for recipe lines that carry a name and no
    linked product. ``meta_data`` answers "what the label on this product
    says", and it is authoritative for that product — a specific flour differs
    from the generic entry, and a value read off a packet must never be
    overwritten by an averaged one.

    Consequence: a product with no nutrition of its own stays without it, even
    when a same-named row exists here. Offering the generic figures as a
    prefill in the manual form is a reasonable future step; adopting them
    silently is not.
    """

    __tablename__ = 'ingredient_nutrition_defaults'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'lang',
            'name_normalized',
            name='uq_ingredient_defaults_org_lang_name',
        ),
        Index(
            'ix_ingredient_defaults_lookup',
            'name_normalized',
            'lang',
            'organization_id',
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    lang: Mapped[str] = mapped_column(String(5), default='en')
    name: Mapped[str] = mapped_column(String(255))
    name_normalized: Mapped[str] = mapped_column(String(255), index=True)

    calories_kcal: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    sugar_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    salt_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    source: Mapped[str] = mapped_column(String(50), default='system')
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class UnitConversion(Base):
    """Culinary-to-metric unit conversion reference.

    organization_id = NULL  -> system defaults (seeded, read-only for users)
    organization_id = <uuid> -> org override (user-managed)

    Lookup order: org override wins over system default.
    """

    __tablename__ = 'unit_conversions'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'ingredient_key',
            'source_unit',
            'lang',
            name='uq_unit_conv_org_ingredient_unit_lang',
        ),
        Index(
            'ix_unit_conv_lookup',
            'ingredient_key',
            'source_unit',
            'lang',
            'organization_id',
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    lang: Mapped[str] = mapped_column(String(5), default='en')
    ingredient_key: Mapped[str] = mapped_column(String(100), index=True)
    ingredient_name: Mapped[str] = mapped_column(String(200))
    source_unit: Mapped[str] = mapped_column(String(50))
    metric_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    metric_unit: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(50), default='other')
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
