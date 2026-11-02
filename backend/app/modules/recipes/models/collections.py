"""RecipeCollection models — hierarchical folders for recipe libraries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models import Organization, User


class RecipeCollection(Base):
    __tablename__ = 'recipe_collections'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'name', name='uq_recipe_collections_org_name'
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    icon: Mapped[str | None] = mapped_column(String(64))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('recipe_collections.id', ondelete='CASCADE'),
        index=True,
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    parent: Mapped[RecipeCollection | None] = relationship(
        'RecipeCollection',
        remote_side=[id],
        back_populates='children',
    )
    children: Mapped[list[RecipeCollection]] = relationship(
        'RecipeCollection',
        back_populates='parent',
        cascade='all, delete-orphan',
        order_by='RecipeCollection.name',
    )
    members: Mapped[list[RecipeCollectionMember]] = relationship(
        'RecipeCollectionMember',
        back_populates='collection',
        cascade='all, delete-orphan',
    )

    organization: Mapped[Organization] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])


class RecipeCollectionMember(Base):
    __tablename__ = 'recipe_collection_members'
    __table_args__ = (
        UniqueConstraint(
            'collection_id', 'recipe_id', name='uq_recipe_collection_members'
        ),
        {'extend_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('recipe_collections.id', ondelete='CASCADE'),
        index=True,
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('recipes.id', ondelete='CASCADE'),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    collection: Mapped[RecipeCollection] = relationship(
        'RecipeCollection', back_populates='members'
    )


__all__ = ['RecipeCollection', 'RecipeCollectionMember']
