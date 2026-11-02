"""Add roles and user_roles tables for RBAC

Revision ID: b2c3d4e5f6a7
Revises: fd08aa0369c1
Create Date: 2026-03-08 00:00:00.000000

"""

import json
import uuid
from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a554e61d446c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# System permission values — must stay in sync with SystemPermission enum.
_ALL_PERMISSIONS: list[str] = [
    'items:read',
    'items:write',
    'items:delete',
    'categories:read',
    'categories:write',
    'storages:read',
    'storages:write',
    'org:read',
    'org:settings:write',
    'org:members:write',
    'admin:access',
    'system:config:write',
]

_USER_PERMISSIONS: list[str] = [
    'items:read',
    'items:write',
    'categories:read',
    'storages:read',
    'org:read',
]


def upgrade() -> None:
    conn = op.get_bind()

    # Check if tables already exist (idempotent — safe for re-deployments
    # where migration ran partially but was not recorded in alembic_version)
    roles_exists = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'roles')"
        )
    ).scalar()
    user_roles_exists = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_roles')"
        )
    ).scalar()

    if not roles_exists:
        op.create_table(
            'roles',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('organization_id', sa.Uuid(), nullable=True),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column(
                'permissions',
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default='[]',
            ),
            sa.Column(
                'is_system',
                sa.Boolean(),
                nullable=False,
                server_default='false',
            ),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ['organization_id'],
                ['organizations.id'],
                name='fk_roles_organization_id',
            ),
            sa.PrimaryKeyConstraint('id'),
            # NOTE: PostgreSQL treats (NULL, 'admin') as distinct from (NULL, 'admin')
            # for UNIQUE constraints, so two system-wide roles with the same name can
            # coexist.  This partial uniqueness is acceptable for the MVP; a
            # partial unique index can be added later if needed.
            sa.UniqueConstraint('organization_id', 'name', name='uq_roles_org_name'),
        )
        op.create_index('ix_roles_organization_id', 'roles', ['organization_id'])

    if not user_roles_exists:
        op.create_table(
            'user_roles',
            sa.Column('user_id', sa.Uuid(), nullable=False),
            sa.Column('role_id', sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ['role_id'],
                ['roles.id'],
                name='fk_user_roles_role_id',
                ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['user_id'],
                ['users.id'],
                name='fk_user_roles_user_id',
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('user_id', 'role_id'),
        )

    # ── Data migration ────────────────────────────────────────────────────────
    # Seed two system-wide roles (organization_id IS NULL, is_system = TRUE).
    # Then assign all existing users to one of these roles based on their
    # current `users.role` string value.
    # Skip seeding if roles already exist.
    now = datetime.now(UTC)
    admin_role_id = str(uuid.uuid4())
    user_role_id = str(uuid.uuid4())

    admin_exists = conn.execute(
        sa.text("SELECT id FROM roles WHERE name = 'admin' AND organization_id IS NULL AND is_system = true LIMIT 1")
    ).fetchone()
    user_exists = conn.execute(
        sa.text("SELECT id FROM roles WHERE name = 'user' AND organization_id IS NULL AND is_system = true LIMIT 1")
    ).fetchone()

    if not admin_exists:
        conn.execute(
            sa.text(
                'INSERT INTO roles '
                '(id, organization_id, name, permissions, is_system, created_at) '
                "VALUES (:id, NULL, 'admin', CAST(:permissions AS jsonb), true, :created_at)"
            ),
            {
                'id': admin_role_id,
                'permissions': json.dumps(_ALL_PERMISSIONS),
                'created_at': now,
            },
        )
    else:
        admin_role_id = str(admin_exists[0])

    if not user_exists:
        conn.execute(
            sa.text(
                'INSERT INTO roles '
                '(id, organization_id, name, permissions, is_system, created_at) '
                "VALUES (:id, NULL, 'user', CAST(:permissions AS jsonb), true, :created_at)"
            ),
            {
                'id': user_role_id,
                'permissions': json.dumps(_USER_PERMISSIONS),
                'created_at': now,
            },
        )
    else:
        user_role_id = str(user_exists[0])

    # Assign users to roles only if not already assigned
    conn.execute(
        sa.text(
            'INSERT INTO user_roles (user_id, role_id) '
            "SELECT id, :role_id FROM users WHERE role = 'admin' "
            'AND id NOT IN (SELECT user_id FROM user_roles WHERE role_id = :role_id)'
        ),
        {'role_id': admin_role_id},
    )
    conn.execute(
        sa.text(
            'INSERT INTO user_roles (user_id, role_id) '
            "SELECT id, :role_id FROM users WHERE (role = 'user' OR role IS NULL) "
            'AND id NOT IN (SELECT user_id FROM user_roles WHERE role_id = :role_id)'
        ),
        {'role_id': user_role_id},
    )


def downgrade() -> None:
    op.drop_table('user_roles')
    op.drop_index('ix_roles_organization_id', table_name='roles')
    op.drop_table('roles')
