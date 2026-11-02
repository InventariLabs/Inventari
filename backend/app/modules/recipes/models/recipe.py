"""Recipe and RecipeIngredient models."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.module_sdk import served_url, stored_reference
from app.database import Base

if TYPE_CHECKING:
    from app.models import Organization, ProductTemplate, Uom, User


class MealSlot(enum.StrEnum):
    LUNCH = 'LUNCH'
    BREAKFAST = 'BREAKFAST'
    DINNER = 'DINNER'
    SNACK = 'SNACK'


class Recipe(Base):
    __tablename__ = 'recipes'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)  # Markdown
    servings: Mapped[int] = mapped_column(Integer, default=1)
    prep_time_minutes: Mapped[int | None] = mapped_column(Integer)
    #: The cover picture's reference, never its address: the org-scoped storage
    #: key the upload wrote (``<org>/recipes/<recipe_id>/cover.<ext>``) or a
    #: foreign ``http(s)`` address for a picture kept from an import.
    #: ``image_url`` below builds the address a reader is given; the column
    #: keeps its historical name.
    image_key: Mapped[str | None] = mapped_column('image_url', Text)
    source_url: Mapped[str | None] = mapped_column(Text)  # original import URL
    tags: Mapped[list[Any] | None] = mapped_column(JSONB)
    is_favorite: Mapped[bool] = mapped_column(default=False, index=True)

    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    organization: Mapped[Organization] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        'RecipeIngredient',
        back_populates='recipe',
        cascade='all, delete-orphan',
        order_by='RecipeIngredient.sort_order',
        lazy='selectin',
    )

    @property
    def ingredients_total(self) -> int:
        """Non-optional ingredient count (mirrors _availability)."""
        return sum(1 for i in self.ingredients if not i.is_optional)

    @property
    def ingredients_linked(self) -> int:
        """Ingredients linked to a product template — the discriminator the
        recipe list empty state needs."""
        return sum(1 for i in self.ingredients if i.template_id is not None)

    @hybrid_property
    def image_url(self) -> str | None:
        """The cover address a reader loads, built from :attr:`image_key`."""
        return served_url(self.image_key)

    @image_url.inplace.setter
    def _image_url_setter(self, value: str | None) -> None:
        self.image_key = stored_reference(value)

    @image_url.inplace.expression
    @classmethod
    def _image_url_expression(cls) -> Any:
        """Filters on the column: ``Recipe.image_url.is_(None)`` keeps working."""
        return cls.image_key


class RecipeIngredient(Base):
    __tablename__ = 'recipe_ingredients'
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('recipes.id', ondelete='CASCADE'),
        index=True,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='SET NULL'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    display_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ingredient_group_name: Mapped[str | None] = mapped_column(String(100), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id', ondelete='SET NULL')
    )
    original_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )
    original_unit_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_optional: Mapped[bool] = mapped_column(default=False)
    #: The cook's own mark from the import review: the amount alone may say
    #: "not a spice" and the mark overrules it. The card reads it beside the
    #: amount when it folds the seasonings section.
    is_spice: Mapped[bool] = mapped_column(default=False)
    picking_skip: Mapped[bool | None] = mapped_column(nullable=True, default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    calories_kcal_per_100g: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id', ondelete='SET NULL'), nullable=True
    )
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # EU 1169/2011 allergen keys (see _allergens.ALLERGEN_KEYS)
    allergens: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    recipe: Mapped[Recipe] = relationship('Recipe', back_populates='ingredients')
    template: Mapped[ProductTemplate | None] = relationship(lazy='selectin')
    uom: Mapped[Uom | None] = relationship(lazy='selectin', foreign_keys=[uom_id])
    price_uom: Mapped[Uom | None] = relationship(
        lazy='selectin', foreign_keys=[price_uom_id]
    )
