"""Grant items:purge to owner/admin roles only.

Revision ID: prgpurge01
Revises: itemweight01
Create Date: 2026-08-17

``items:purge`` splits the irreversible purge from the reversible archive:
until now both sat behind ``items:delete``, so anyone who could archive could
also permanently delete.

The new permission is deliberately NOT inherited from ``items:delete``. This
migration grants it only to roles named ``owner`` or ``admin`` (system or
org-scoped); every other role keeps its set unchanged, even if it holds
``items:delete`` today — purge must be granted explicitly through the RBAC
matrix. Users with ``User.role='admin'`` are unaffected: ``has_permission``
bypasses checks for admins regardless of role rows.

Downgrade removes the key from those roles again.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'prgpurge01'
down_revision: str | None = 'itemweight01'
branch_labels: str | None = None
depends_on: str | None = None

_PERMISSION = 'items:purge'


def upgrade() -> None:
    # JSONB || appends the string as an array element; `?` checks for a
    # top-level string element. Role names are static, not user input.
    op.get_bind().exec_driver_sql(
        """
        UPDATE roles
        SET permissions = permissions || to_jsonb(%s::text)
        WHERE lower(name) IN ('owner', 'admin')
          AND NOT (permissions ? %s)
        """,
        (_PERMISSION, _PERMISSION),
    )


def downgrade() -> None:
    # JSONB `-` removes every occurrence of the string element.
    op.get_bind().exec_driver_sql(
        """
        UPDATE roles
        SET permissions = permissions - %s
        WHERE lower(name) IN ('owner', 'admin')
        """,
        (_PERMISSION,),
    )
