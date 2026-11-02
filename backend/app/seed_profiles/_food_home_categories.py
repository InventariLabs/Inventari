"""Orchestrator for the Food & Home category seed.

The category data lives in three sibling modules (one per storage type),
grouped by storage type:

  - :mod:`._food_home_categories_freezer` — FREEZER rows
  - :mod:`._food_home_categories_fridge`  — FRIDGE rows
  - :mod:`._food_home_categories_pantry`  — PANTRY + universal 'Other'

The persistence loop stays here.

``group_label`` is seeded as a code — ``FRIDGE``, ``FREEZER``, ``PANTRY`` —
and not as a readable name, on purpose. The interface has a word for each of
them in all five languages (``categories:groups.*``), so a code is the one
value that reads correctly in every one; a name seeded in English would be
English on a Polish screen for good, because a label the organisation owns is
not something later releases may rewrite. Anything an organisation types
itself is a label and is shown exactly as typed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.category import Category

from ._food_home_categories_freezer import FREEZER_CATEGORIES
from ._food_home_categories_fridge import FRIDGE_CATEGORIES
from ._food_home_categories_pantry import PANTRY_CATEGORIES

logger = get_logger(__name__)


def seed_food_categories(
    db: Session,
    *,
    organization_id: UUID | None = None,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Add food product categories with context_tags set for each storage context.

    Args:
        db: Active SQLAlchemy session.
        organization_id: Owner of the seeded rows. A domain catalogue belongs
            to the organization that asked for it (AGENTS.md §4) — category
            reads surface ``organization_id IS NULL`` rows to *every* tenant,
            so seeding one organization's profile without an owner fills the
            category list of everyone else on the installation, neutral
            workspace modes included.
            ``None`` seeds the installation-wide catalogue and is reserved for
            single-tenant boot (``python -m app.seed_data``)
            and the integration-test snapshot; onboarding and profile
            switching always pass an owner.
        insert_only: When True, existing rows are left untouched; only
            missing rows are inserted. Lookup uses the stable ``code``
            (not ``name``) so a renamed category is not duplicated.
        commit: When True (default), commits at the end.
    """
    categories: list[dict[str, Any]] = [
        *FREEZER_CATEGORIES,
        *FRIDGE_CATEGORIES,
        *PANTRY_CATEGORIES,
    ]

    owner_filter = (
        Category.organization_id.is_(None)
        if organization_id is None
        else Category.organization_id == organization_id
    )

    for cat_data in categories:
        # Lookup by stable `code` rather than `name` so a renamed
        # category is recognised as existing and not duplicated.
        existing = db.scalars(
            select(Category).where(
                Category.code == cat_data['code'],
                owner_filter,
            )
        ).first()
        if not existing:
            cat = Category(**cat_data, organization_id=organization_id)
            db.add(cat)
        elif not insert_only:
            existing.code = cat_data['code']
            existing.icon = cat_data['icon']
            existing.sort_order = cat_data['sort_order']
            # The group the organisation sees and can edit.
            existing.group_label = cat_data['group_label']
            existing.context_tag = cat_data.get('context_tag')
            if 'field_definitions' in cat_data:
                existing.field_definitions = cat_data['field_definitions']

    if commit:
        try:
            db.commit()
            logger.info('[food_home] Added %d food categories', len(categories))
        except SQLAlchemyError:
            db.rollback()
            raise
    else:
        db.flush()
