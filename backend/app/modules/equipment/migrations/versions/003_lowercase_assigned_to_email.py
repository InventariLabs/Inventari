"""equipment: lowercase assigned_to_email in equipment_assignments.

The checkout used to store ``assigned_to_email`` verbatim, so
"Anna.Kowalska@Example.org" stayed mixed-case in the database while "My
assets" compared it with a bare ``==`` against the lowercase account
email. Emails are case-insensitive (RFC 5321): this migration normalizes
existing rows, and the write path now lowercases on insert.

* Upgrade — rewrites every non-null ``assigned_to_email`` to lowercase.
  Idempotent: re-running only touches rows that still differ.
* Downgrade — no-op. The original casing is not recoverable from the
  normalized value; reverting the code change is what restores the old
  write behavior.

Revision ID: 003_lowercase_assigned_to_email
Revises: 002_fix_seeded_storage_usage
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '003_lowercase_assigned_to_email'
down_revision: str | None = '002_fix_seeded_storage_usage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE equipment_assignments
        SET assigned_to_email = lower(assigned_to_email)
        WHERE assigned_to_email IS NOT NULL
          AND assigned_to_email <> lower(assigned_to_email)
        """
    )


def downgrade() -> None:
    # Data normalization is one-way: the original casing is lost.
    pass
