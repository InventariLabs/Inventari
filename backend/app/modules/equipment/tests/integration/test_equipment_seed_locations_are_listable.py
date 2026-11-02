"""Equipment module seed locations must be listable.

Bug: ``module.py`` seeded ``Server Room`` and ``IT Storage`` with
``usage='active'``, which is not a valid ``LocationUsage`` value. The
``usage`` column is a plain ``String(50)`` so the invalid string was
silently stored and the rows became invisible to ``GET /api/v1/locations``
(default ``usage='internal'`` filter).

Two contracts enforced here:

1. The seed (now declared in module metadata and applied by
   ``BaseModule.system_on_enable``) must create rows with
   ``usage='internal'``.
2. Migration ``002_fix_seeded_storage_usage`` must repair legacy
   ``usage='active'`` rows where ``context_tag='equipment'`` and leave
   unrelated rows alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import run_module_migrations
from app.database import Base
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.module import EquipmentModule


async def _seed_default_locations_async(
    session: AsyncSession,
) -> tuple[Organization, User]:
    """Enable the equipment seed via ``system_on_enable`` and commit.

    Creates a fresh org + admin user (the framework hook needs a user as
    the ``created_by`` of seeded locations). Returns the pair.
    """
    org = Organization(
        name=f'Seed Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core'],
    )
    session.add(org)
    await session.flush()
    user = User(
        email=f'user_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Seeder',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    session.add(user)
    await session.flush()

    await EquipmentModule().system_on_enable(
        org.id,
        session,
        user=UserContextDTO(id=user.id, organization_id=org.id, role='admin'),
    )
    await session.commit()
    return org, user


async def _seeded_rows_async(
    session: AsyncSession, org: Organization
) -> list[StorageLocation]:
    result = await session.execute(
        select(StorageLocation).where(
            StorageLocation.organization_id == org.id,
            StorageLocation.context_tag == 'equipment',
        )
    )
    return list(result.scalars())


# ---------------------------------------------------------------------------
# (1) Seed correctness — system_on_enable creates rows with usage='internal'
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSystemOnEnableSeeding:
    """Declared default locations seed with usage='internal', not 'active'."""

    async def test_seeded_locations_have_internal_usage(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """The seed creates rows with usage='internal'."""
        org, _user = await _seed_default_locations_async(real_async_db_session)
        rows = await _seeded_rows_async(real_async_db_session, org)

        names = {r.name for r in rows}
        assert names == {'Server Room', 'IT Storage'}, (
            f'Expected default seeds to exist; got names={names}'
        )
        assert all(r.usage == 'internal' for r in rows), (
            'Seeded equipment storages must carry usage="internal" '
            f'for default /storages visibility. Found: {[(r.name, r.usage) for r in rows]}'
        )

    async def test_seeded_locations_not_recreated_when_present(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """Re-running system_on_enable is idempotent (still exactly 2 rows)."""
        org, user = await _seed_default_locations_async(real_async_db_session)
        first = await _seeded_rows_async(real_async_db_session, org)

        await EquipmentModule().system_on_enable(
            org.id,
            real_async_db_session,
            user=UserContextDTO(id=user.id, organization_id=org.id, role='admin'),
        )
        await real_async_db_session.commit()
        second = await _seeded_rows_async(real_async_db_session, org)

        assert len(first) == len(second) == 2


# ---------------------------------------------------------------------------
# (2) Corrective migration — upgrade + downgrade + idempotency
# ---------------------------------------------------------------------------


@pytest.fixture(scope='class')
def isolated_db_url() -> Iterator[str]:
    """An empty database shared across all tests in this class."""
    with _isolated_db_url('e2') as test_url:
        yield test_url


@pytest.fixture(scope='class')
def isolated_db_with_seed(isolated_db_url: str) -> str:
    """Isolated DB at head with two legacy 'active' rows + two control rows.

    Order of operations:
      1. Create core tables (Base.metadata.create_all, exclude equipment's).
      2. Upgrade equipment to ``001_initial`` (creates module tables only,
         no data rows yet).
      3. Insert two legacy ``usage='active'`` equipment rows + one
         pre-existing ``usage='internal'`` row + one unrelated
         ``usage='active'`` row outside the equipment context.
      4. Downgrade equipment to ``001_initial`` (drops module tables, leaves
         core data untouched).
      5. Upgrade equipment back to head — this re-creates module tables and
         runs migration ``002_fix_seeded_storage_usage`` on the now-existing
         legacy rows, flipping ``active`` → ``internal`` only for them.

    Final state expected:
      - 'Server Room'        usage='internal' context_tag='equipment'
      - 'IT Storage'         usage='internal' context_tag='equipment'
      - 'Pre-existing Spot'  usage='internal' context_tag='equipment'
      - 'Random non-eq'      usage='active'   context_tag=NULL
    """
    import app.core.template_models  # noqa: F401
    import app.models  # noqa: F401
    import app.modules.equipment.models  # noqa: F401

    engine = create_engine(isolated_db_url)
    module_tables = {
        'audit_campaigns',
        'audit_responses',
        'audit_response_items',
        'equipment_assignments',
        'equipment_attachments',
        'equipment_document_templates',
        'equipment_maintenance_logs',
    }
    core_tables = [
        t for t in Base.metadata.sorted_tables if t.name not in module_tables
    ]
    Base.metadata.create_all(engine, tables=core_tables)
    engine.dispose()

    # Step 2: create module tables only.
    run_module_migrations(
        'equipment', 'upgrade', db_url=isolated_db_url, revision='001_initial'
    )

    engine = create_engine(isolated_db_url)
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO organizations (id, name, enabled_modules, created_at, settings)
                VALUES (:id, :name, :mods, now(), '{}'::jsonb)
                """
            ),
            {
                'id': org_id,
                'name': 'Legacy Org',
                'mods': '["core","items","equipment"]',
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, hashed_password, is_active,
                                    organization_id, role, created_at, updated_at)
                VALUES (:id, :email, :pwd, true, :org, 'admin', now(), now())
                """
            ),
            {
                'id': user_id,
                'email': 'legacy@example.com',
                'pwd': 'x',
                'org': org_id,
            },
        )
        # Step 3: legacy rows.
        conn.execute(
            text(
                """
                INSERT INTO storage_locations
                  (id, organization_id, name, usage, context_tag, created_by, created_at)
                VALUES
                  (:id1, :org, 'Server Room',       'active',   'equipment', :user, now()),
                  (:id2, :org, 'IT Storage',        'active',   'equipment', :user, now()),
                  (:id3, :org, 'Pre-existing Spot', 'internal', 'equipment', :user, now()),
                  (:id4, :org, 'Random non-eq',     'active',   NULL,        :user, now())
                """
            ),
            {
                'id1': uuid.uuid4(),
                'id2': uuid.uuid4(),
                'id3': uuid.uuid4(),
                'id4': uuid.uuid4(),
                'org': org_id,
                'user': user_id,
            },
        )
        conn.commit()
    engine.dispose()

    # Step 4: drop module tables so step 5 can run the data-only migration
    # against the pre-existing legacy rows.
    run_module_migrations(
        'equipment', 'downgrade', db_url=isolated_db_url, revision='base'
    )

    # Step 5: re-run upgrade to head — creates module tables again and runs
    # the corrective data migration 002_fix_seeded_storage_usage.
    run_module_migrations(
        'equipment', 'upgrade', db_url=isolated_db_url, revision='head'
    )

    return isolated_db_url


def _read_rows(db_url: str) -> list[tuple[str, str | None, str | None]]:
    """Return (name, usage, context_tag) for all storage_locations."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text('SELECT name, usage, context_tag FROM storage_locations ORDER BY name')
        ).all()
    engine.dispose()
    return [(r[0], r[1], r[2]) for r in rows]


@pytest.mark.integration
class TestCorrectiveMigration:
    """002_fix_seeded_storage_usage: upgrade and downgrade correctness."""

    MODULE = 'equipment'

    def test_upgrade_fixes_legacy_active_rows(self, isolated_db_with_seed: str) -> None:
        """Rows with usage='active' AND context_tag='equipment' become 'internal'."""
        rows = _read_rows(isolated_db_with_seed)
        by_name = {name: (usage, tag) for name, usage, tag in rows}
        # The two seeds are repaired; the pre-existing 'internal' row is
        # untouched.
        assert by_name['Server Room'] == ('internal', 'equipment')
        assert by_name['IT Storage'] == ('internal', 'equipment')
        assert by_name['Pre-existing Spot'] == ('internal', 'equipment')

    def test_upgrade_leaves_unrelated_active_row_alone(
        self, isolated_db_with_seed: str
    ) -> None:
        """A row with usage='active' but NO equipment tag must NOT be modified."""
        rows = _read_rows(isolated_db_with_seed)
        by_name = {name: (usage, tag) for name, usage, tag in rows}
        assert by_name['Random non-eq'] == ('active', None)

    def test_upgrade_is_idempotent(self, isolated_db_with_seed: str) -> None:
        """Re-running upgrade@head leaves the DB unchanged."""
        # Fixture already ran upgrade@head once. Run it again.
        run_module_migrations(
            self.MODULE, 'upgrade', db_url=isolated_db_with_seed, revision='head'
        )

        engine = create_engine(isolated_db_with_seed)
        with engine.connect() as conn:
            count = conn.execute(
                text(
                    'SELECT COUNT(*) FROM storage_locations '
                    "WHERE context_tag='equipment' AND usage='active'"
                )
            ).scalar()
        engine.dispose()
        assert count == 0

    def test_downgrade_restores_active_for_seed_names(
        self, isolated_db_with_seed: str
    ) -> None:
        """Downgrade rewrites 'internal' -> 'active' for known seed names only."""
        run_module_migrations(
            self.MODULE,
            'downgrade',
            db_url=isolated_db_with_seed,
            revision='001_initial',
        )
        try:
            rows = _read_rows(isolated_db_with_seed)
        finally:
            # The fixture is shared by the class and promises a database at
            # head; the upgrade tests read that promise, in whatever order
            # they run.
            run_module_migrations(
                self.MODULE, 'upgrade', db_url=isolated_db_with_seed, revision='head'
            )
        by_name = {name: (usage, tag) for name, usage, tag in rows}
        # Downgrade scope: only the two seed names revert; pre-existing
        # 'internal' row stays 'internal' (its name is not a known seed).
        assert by_name['Server Room'] == ('active', 'equipment')
        assert by_name['IT Storage'] == ('active', 'equipment')
        assert by_name['Pre-existing Spot'] == ('internal', 'equipment')
        # The unrelated non-equipment row must be untouched.
        assert by_name['Random non-eq'] == ('active', None)
