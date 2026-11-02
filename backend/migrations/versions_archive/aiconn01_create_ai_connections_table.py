"""create ai_connections table

Foundational schema piece of the AI Connections Registry.

This is a SCHEMA-ONLY migration: zero data changes. Per AGENTS.md
§Backend.5 "no data migrations in schema files", the corresponding data
migration (legacy ``settings.llm`` -> ``ai_connections`` rows) lives in
its own Alembic file (``aiconn02``).

Table shape:
  - id UUID PK
  - organization_id UUID FK organizations(id) ON DELETE CASCADE, indexed
  - name VARCHAR(255) NOT NULL
  - provider VARCHAR(50) NOT NULL                (loose varchar, not Postgres ENUM
                                                    — adding a provider needs no migration)
  - api_key_enc VARCHAR NOT NULL DEFAULT ''      (empty string = no key, kept in
                                                    sync with crypto_service.encrypt_value)
  - api_base_url VARCHAR(512) NOT NULL DEFAULT ''
  - model_name VARCHAR(255) NOT NULL DEFAULT ''
  - temperature FLOAT NULL                        (NULL = use provider SDK default)
  - max_tokens  INTEGER NULL
  - top_p       FLOAT NULL
  - capabilities JSONB NOT NULL DEFAULT '[]'     (list[str])
  - created_at TIMESTAMP NOT NULL
  - updated_at TIMESTAMP NOT NULL

Constraints:
  - uq_ai_connections_org_name UNIQUE (organization_id, name)
    Per design: name uniqueness is per-org, not global. Two orgs may
    each have a connection named "Default".

Naming: ``aiconn01_create_ai_connections_table``. The ``aiconn01``
prefix follows the project's convention of grouping topical migrations
(bughunt01, stockmove01, cv2_emoji_color_001, ...).

Revision ID: aiconn01
Revises: cv2_emoji_color_001
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'aiconn01'
down_revision: str | None = 'cv2_emoji_color_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'ai_connections',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column(
            'api_key_enc',
            sa.String(),
            nullable=False,
            server_default='',
        ),
        sa.Column(
            'api_base_url',
            sa.String(length=512),
            nullable=False,
            server_default='',
        ),
        sa.Column(
            'model_name',
            sa.String(length=255),
            nullable=False,
            server_default='',
        ),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        sa.Column('top_p', sa.Float(), nullable=True),
        sa.Column(
            'capabilities',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'ix_ai_connections_organization_id',
        'ai_connections',
        ['organization_id'],
        unique=False,
    )
    op.create_unique_constraint(
        'uq_ai_connections_org_name',
        'ai_connections',
        ['organization_id', 'name'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_ai_connections_org_name', 'ai_connections')
    op.drop_index('ix_ai_connections_organization_id', 'ai_connections')
    op.drop_table('ai_connections')
