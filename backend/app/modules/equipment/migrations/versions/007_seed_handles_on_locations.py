"""equipment: give the seeded locations a handle the interface can translate.

Enabling the module seeds "Server Room" and "IT Storage". Those names are
written to the database in English and then read by people working in five
languages — the first thing a Polish user sees in the location dropdown is
two English strings, indistinguishable from data they typed themselves.

Names stay editable, so the translation cannot hang off the name. The seeder
now records a code and the name it wrote under ``settings['seed']``, and a
client translates the code only while the name still matches. This migration
gives organizations seeded before that the same handle, matching on the name
the seeder used and only where the row still carries it.

* Upgrade — stamps ``settings['seed']`` on equipment-tagged locations still
  named as seeded. Idempotent; renamed rows are left alone, which is the
  point — their name is the user's.
* Downgrade — removes the ``seed`` key again, leaving other settings intact.

Revision ID: 007_seed_handles_on_locations
Revises: 006_reconcile_equipment_status
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '007_seed_handles_on_locations'
down_revision: str | None = '006_reconcile_equipment_status'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # storage_locations.settings is `json`, not `jsonb` — every operator below
    # needs the cast, and the result has to go back as json.
    for code, seeded_name in (
        ('SERVER_ROOM', 'Server Room'),
        ('IT_STORAGE', 'IT Storage'),
    ):
        op.execute(
            f"""
            UPDATE storage_locations
            SET settings = (
                coalesce(settings::jsonb, '{{}}'::jsonb)
                || jsonb_build_object(
                    'seed', jsonb_build_object('code', '{code}', 'name', name)
                )
            )::json
            WHERE context_tag = 'equipment'
              AND name = '{seeded_name}'
              AND NOT (coalesce(settings::jsonb, '{{}}'::jsonb) ? 'seed')
            """  # noqa: S608 - literals above, no caller input
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE storage_locations
        SET settings = (settings::jsonb - 'seed')::json
        WHERE context_tag = 'equipment'
          AND settings::jsonb ? 'seed'
        """
    )
