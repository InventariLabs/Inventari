"""
Food & Home seed profile.

Contains:
  - Food-oriented storage types: FREEZER, FRIDGE, PANTRY, MEDICINE_CABINET
  - Food product categories (frozen, fridge, pantry) with context_tag set
  - US kitchen units of measure (cup, pint, quart, gallon, fluid ounce)
  - One universal "Other" category

This profile should be applied when the user selects the "Food & Home"
starter pack during onboarding. It is additive: calling seed_base_all()
first is recommended but not required (seed_food_home handles it).
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.seed_profiles.base import seed_base_all, seed_uom

from ._food_home_categories import seed_food_categories
from ._food_home_storage_types import seed_food_storage_types
from ._uom_data import UOM_UNITS_US_KITCHEN


def seed_food_home(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Apply the full Food & Home profile: base + food storage types + food categories.

       ``organization_id`` owns the seeded categories and storage types alike —
    a profile is chosen by one tenant. Units of measure stay
       installation-wide; they have no owner column. The US kitchen measures
    (cup, pint, quart, gallon, fluid ounce) come in here, not with the
    neutral base — a workspace in the neutral mode has no use for them.
    """
    seed_base_all(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
    seed_uom(
        db,
        units=UOM_UNITS_US_KITCHEN,
        insert_only=insert_only,
        commit=commit,
    )
    seed_food_storage_types(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
    seed_food_categories(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
