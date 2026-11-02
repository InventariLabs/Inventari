"""Storage types become per-organization rows instead of installation-wide ones.

Revision ID: orgsttype01
Revises: invrole01
Create Date: 2026-08-23

Every storage type was written with ``organization_id IS NULL``: the profile
one tenant picked at onboarding seeded types the whole installation read, and
a module's declared types were synced once at application startup for every
tenant whether or not they had the module. Categories were moved to per-tenant
rows already; this is the same move for the other table that carried
system rows from the single-tenant era.

The copy is not indiscriminate. An organization gets:

* the neutral base every tenant needs (``SHELF``, ``STORAGE_ROOM``,
  ``SYSTEM`` — without the last one it cannot book consumption at all),
* the set its ``active_profile_id`` seeds; no profile is read as the neutral
  one, the same default the seeder uses,
* the types declared by the modules in its ``enabled_modules``,
* and every global type it currently has a location standing on, whatever the
  code — that is what keeps this migration lossless for hand-made and retired
  types alike.

The code sets are written out here rather than imported: a migration records
the world as it was on this date, and reading today's declarations would make
it change meaning every time a module adds a type.

Order matters. Copies first, then the location remap, and only then the
delete — ``storage_locations.storage_type_id`` is a foreign key without
``ondelete``, so removing a global row while anything points at it fails loudly
instead of quietly dropping a type.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'orgsttype01'
down_revision: str | None = 'invrole01'
branch_labels: str | None = None
depends_on: str | None = None


NEUTRAL_CODES = ('SHELF', 'STORAGE_ROOM', 'SYSTEM')

PROFILE_CODES = {
    'clean_core': (),
    'food_home': ('FREEZER', 'FRIDGE', 'PANTRY', 'MEDICINE_CABINET'),
    'equipment_wms': ('TOOL_ROOM', 'ASSET_STORAGE', 'IT_RACK', 'MAINTENANCE_BAY'),
}

MODULE_CODES = {
    'equipment': ('SERVER_ROOM', 'IT_STORAGE'),
}

DEFAULT_PROFILE = 'clean_core'


def upgrade() -> None:
    conn = op.get_bind()

    globals_by_code = {
        row.type_code: row
        for row in conn.execute(
            sa.text(
                'SELECT id, type_code FROM storage_types WHERE organization_id IS NULL'
            )
        )
    }
    if not globals_by_code:
        return

    organizations = conn.execute(
        sa.text('SELECT id, active_profile_id, enabled_modules FROM organizations')
    ).fetchall()

    remapped = 0
    for org in organizations:
        wanted: set[str] = set(NEUTRAL_CODES)
        profile = org.active_profile_id or DEFAULT_PROFILE
        wanted.update(PROFILE_CODES.get(profile, ()))
        for module_name in org.enabled_modules or []:
            wanted.update(MODULE_CODES.get(module_name, ()))

        in_use = {
            row.type_code
            for row in conn.execute(
                sa.text(
                    'SELECT DISTINCT st.type_code '
                    'FROM storage_locations sl '
                    'JOIN storage_types st ON st.id = sl.storage_type_id '
                    'WHERE sl.organization_id = :org '
                    'AND st.organization_id IS NULL'
                ),
                {'org': org.id},
            )
        }
        wanted.update(in_use)

        owned = {
            row.type_code: row.id
            for row in conn.execute(
                sa.text(
                    'SELECT id, type_code FROM storage_types '
                    'WHERE organization_id = :org'
                ),
                {'org': org.id},
            )
        }

        for code in sorted(wanted):
            source = globals_by_code.get(code)
            if source is None or code in owned:
                continue
            # INSERT ... SELECT so the JSON columns (context_schema,
            # field_definitions, default_settings) are copied as they are
            # rather than round-tripped through the driver.
            new_id = conn.execute(
                sa.text(
                    'INSERT INTO storage_types '
                    '(id, name, type_code, icon, behavior_mode, context_schema, '
                    'field_definitions, default_settings, is_system, '
                    'organization_id) '
                    'SELECT gen_random_uuid(), name, type_code, icon, '
                    'behavior_mode, context_schema, field_definitions, '
                    'default_settings, is_system, :org '
                    'FROM storage_types WHERE id = :source '
                    'RETURNING id'
                ),
                {'org': org.id, 'source': source.id},
            ).scalar()
            owned[code] = new_id

        # Point this organization's locations at its own copies.
        for code, source in globals_by_code.items():
            target_id = owned.get(code)
            if target_id is None:
                continue
            result = conn.execute(
                sa.text(
                    'UPDATE storage_locations SET storage_type_id = :target '
                    'WHERE organization_id = :org AND storage_type_id = :source'
                ),
                {'target': target_id, 'org': org.id, 'source': source.id},
            )
            remapped += result.rowcount or 0

    print(f'orgsttype01: remapped {remapped} storage_locations rows')

    orphaned = conn.execute(
        sa.text(
            'SELECT count(*) FROM storage_locations sl '
            'JOIN storage_types st ON st.id = sl.storage_type_id '
            'WHERE st.organization_id IS NULL'
        )
    ).scalar()
    if orphaned:
        raise RuntimeError(
            f'orgsttype01: {orphaned} storage_locations still point at a global '
            'storage type — refusing to delete the global rows'
        )

    conn.execute(sa.text('DELETE FROM storage_types WHERE organization_id IS NULL'))


def downgrade() -> None:
    """Restore one installation-wide row per code and point locations back.

    Asymmetric on purpose: the per-organization copies stay. Nothing records
    which of them this migration created and which a tenant made afterwards,
    and deleting the wrong one would take its locations' type with it. The
    read path before this revision deduplicates by code and prefers the
    organization's own row, so the leftovers are invisible rather than
    harmful.
    """
    conn = op.get_bind()

    codes = [
        row.type_code
        for row in conn.execute(
            sa.text(
                'SELECT DISTINCT type_code FROM storage_types '
                'WHERE organization_id IS NOT NULL AND is_system IS TRUE'
            )
        )
    ]
    for code in codes:
        existing = conn.execute(
            sa.text(
                'SELECT id FROM storage_types '
                'WHERE organization_id IS NULL AND type_code = :code'
            ),
            {'code': code},
        ).scalar()
        if existing is None:
            existing = conn.execute(
                sa.text(
                    'INSERT INTO storage_types '
                    '(id, name, type_code, icon, behavior_mode, is_system, '
                    'organization_id) '
                    'SELECT gen_random_uuid(), name, type_code, icon, '
                    'behavior_mode, TRUE, NULL FROM storage_types '
                    'WHERE organization_id IS NOT NULL AND type_code = :code '
                    'LIMIT 1 RETURNING id'
                ),
                {'code': code},
            ).scalar()
        conn.execute(
            sa.text(
                'UPDATE storage_locations SET storage_type_id = :target '
                'WHERE storage_type_id IN ('
                '  SELECT id FROM storage_types '
                '  WHERE organization_id IS NOT NULL AND type_code = :code'
                ')'
            ),
            {'target': existing, 'code': code},
        )
