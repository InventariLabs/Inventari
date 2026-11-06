"""
Script for initializing seed data in the database.
Run: python -m app.seed_data

Seed profiles (applied to one organization, by `manage.py db seed --profile`
or when the organization is onboarded):
    clean_core    (default) neutral storage types
    food_home     food storage types + food categories
    equipment_wms warehouse storage types

Without an organization only the installation-wide data is seeded: units of
measure, the one seed table with no owner column.
"""

import importlib
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.operator_error import OperatorError
from app.core.product_profiles import DEFAULT_PROFILE_ID

logger = get_logger(__name__)

__all__ = [
    'seed_all',
    'seed_all_async',
    # Backward-compat re-export (used by conftest fixtures and legacy tests)
    'seed_uom',
]

from app._seed_uom import seed_uom  # noqa: E402

_PROFILE_MAP = {
    'clean_core': 'app.seed_profiles.clean_core.seed_clean_core',
    'food_home': 'app.seed_profiles.food_home.seed_food_home',
    'equipment_wms': 'app.seed_profiles.equipment_wms.seed_equipment_wms',
}


def _get_seeder(profile: str):
    """Resolve profile name to seed function."""
    dotted = _PROFILE_MAP.get(profile)
    if dotted is None:
        raise OperatorError(
            f"Unknown seed profile '{profile}'. Available: {', '.join(_PROFILE_MAP)}"
        )
    module_path, func_name = dotted.rsplit('.', 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)


def seed_all(
    profile: str | None = None,
    organization_id: UUID | None = None,
    insert_only: bool = True,
):
    """Initialize seed data (sync — for CLI use).

       Args:
           profile: Seed profile name. Defaults to 'clean_core'. Ignored
                    without *organization_id* —
                    everything a profile brings except units of measure is
    owned by one tenant.
           organization_id: The organization the profile is applied to. When
                    omitted only the installation-wide data (UoM) is seeded,
                    which is all a database with no organizations can hold.
           insert_only: When True (the default) rows that already exist are
                    left as they are. ``False`` refreshes their definitions;
                    a name the organization has changed stays protected in
                    both modes — see ``upsert_storage_types``.
    """
    from app._seed_uom import seed_uom as _seed_uom
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if organization_id is None:
            logger.info('Seeding installation-wide data (no organization given)')
            _seed_uom(db, insert_only=insert_only)
            logger.info('Seed data added successfully!')
            return

        profile = profile or DEFAULT_PROFILE_ID
        seeder = _get_seeder(profile)
        logger.info(f'Seeding with profile: {profile} for org {organization_id}')
        seeder(db, organization_id=organization_id, insert_only=insert_only)
        logger.info('Seed data added successfully!')
    finally:
        db.close()


def list_seedable_organizations(db: Session) -> list[tuple[UUID, str]]:
    """Organizations a profile can be applied to, oldest first.

    A profile belongs to one tenant (AGENTS.md §4), so the command that applies
    one has to know which tenants exist before it can tell "the only
    organization there is" from "pick one".
    """
    from sqlalchemy import select

    from app.models.organization import Organization

    rows = db.execute(
        select(Organization.id, Organization.name).order_by(
            Organization.created_at, Organization.id
        )
    ).all()
    return [(row.id, row.name) for row in rows]


#: Arbitrary constant shared by every process that seeds the installation-wide
#: data at boot; distinct from the migration lock's key.
SEED_LOCK_KEY = 727302


async def seed_all_async():
    """Seed the installation-wide data at boot (async — for lifespan use).

    Only units of measure: they have no owner column. Storage types and
    categories belong to an organization, and at first boot there is none —
    they are seeded when an organization is created and when it picks a
    profile (``apply_profile_seed``).

    No-ops once UoM rows exist (first-boot indicator).

    Every worker of a fresh install runs this at the same moment. Each read an
    empty ``uoms`` table before any of them had written, and the second to
    insert the Pack reference unit broke ``uq_uom_category_reference``. The
    workers now queue on a transaction-scoped advisory lock — released at the
    commit, so the next one finds the rows and skips — and it holds through a
    transaction-mode pooler, where a session-scoped one would not.
    """
    from sqlalchemy import text

    from app._seed_uom import seed_uom as _seed_uom
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:  # type: ignore[misc]
        await db.execute(
            text('SELECT pg_advisory_xact_lock(:key)'), {'key': SEED_LOCK_KEY}
        )
        result = await db.execute(text('SELECT COUNT(*) FROM uoms'))
        count = result.scalar()
        if count and count > 0:
            logger.debug('Seed data already present, skipping.')
            return

        logger.info('Seeding units of measure')
        await db.run_sync(_seed_uom)
        await db.commit()
        logger.info('Seed data added successfully!')


if __name__ == '__main__':
    seed_all()
