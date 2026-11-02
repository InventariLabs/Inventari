"""Installation-wide unit seeding for the non-profile boot path.

Kept as its own entry point because ``app.seed_data`` and the CLI call it by
name; the catalogue and the writing both live in
:mod:`app.seed_profiles.base`, so the two paths cannot drift again. They had:
twenty units here, sixteen there, and ``rounding`` on one side only.
"""

from sqlalchemy.orm import Session

from app.seed_profiles.base import seed_uom as _seed_uom_base


def seed_uom(db: Session, *, insert_only: bool = False, commit: bool = True) -> None:
    """Add the standard Units of Measure.

    ``insert_only`` defaults to False, which is the boot path's behaviour: the
    run corrects the one property the catalogue owns (a unit seeded before the
    catalogue carried ``rounding`` took the column default) and leaves names,
    factors and symbols as the installation has them. A seed run that promised
    to leave existing rows alone passes True.
    """
    _seed_uom_base(db, insert_only=insert_only, commit=commit)
