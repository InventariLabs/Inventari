"""add_system_settings_and_cost_is_estimated

Revision ID: 972ff3fa353b
Revises: c4fb9b760dbe
Create Date: 2026-02-22 09:22:29.645959

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '972ff3fa353b'
down_revision: Union[str, None] = 'c4fb9b760dbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('key'),
    )
    op.add_column(
        'ai_usage_logs',
        sa.Column('cost_is_estimated', sa.Boolean(), server_default='false', nullable=False),
    )
    op.create_index(
        op.f('ix_ai_usage_logs_created_at'), 'ai_usage_logs', ['created_at'], unique=False
    )

    # Seed default system settings
    op.execute("""
        INSERT INTO system_settings (key, value, updated_at) VALUES
        ('model_pricing', '{
            "google/gemini-2.0-flash-001":      {"input_per_1k": 0.000075, "output_per_1k": 0.0003},
            "google/gemini-2.0-flash-exp:free": {"input_per_1k": 0.0,      "output_per_1k": 0.0},
            "google/gemini-1.5-pro":            {"input_per_1k": 0.00125,  "output_per_1k": 0.005},
            "openai/gpt-4o":                    {"input_per_1k": 0.0025,   "output_per_1k": 0.01},
            "openai/gpt-4o-mini":               {"input_per_1k": 0.00015,  "output_per_1k": 0.0006},
            "qwen/qwen-vl-plus":                {"input_per_1k": 0.0008,   "output_per_1k": 0.0008}
        }', NOW()),
        ('default_org_limits', '{
            "ai_scans_monthly": null,
            "ai_requests_monthly": null,
            "max_products": null,
            "max_members": null
        }', NOW())
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_usage_logs_created_at'), table_name='ai_usage_logs')
    op.drop_column('ai_usage_logs', 'cost_is_estimated')
    op.drop_table('system_settings')
