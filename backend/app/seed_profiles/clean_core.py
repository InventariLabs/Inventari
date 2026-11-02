"""
Seed profile for the neutral workspace mode (`clean_core`).

Minimal neutral defaults only — no food, no equipment, no domain assumptions.
Suitable for verticals that want to shape their own configuration after
onboarding. The mode is called "Custom" on screen; `clean_core` is the
identifier it is stored under. See docs/MODULE_NAMES.md § "Workspace mode
names".
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.seed_profiles.base import seed_base_all


def seed_clean_core(
    db: Session,
    *,
    organization_id: UUID,
    insert_only: bool = False,
    commit: bool = True,
) -> None:
    """Apply the minimal neutral profile: UoM + neutral storage types only.

    ``organization_id`` owns the seeded storage types; units of
       measure are installation-wide and have no owner column.
    """
    seed_base_all(
        db,
        organization_id=organization_id,
        insert_only=insert_only,
        commit=commit,
    )
