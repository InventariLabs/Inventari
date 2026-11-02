"""printing module — the handshake records what the agent is and what it speaks.

An agent runs on a machine nobody here controls, so the registration is the
only place that can say which build stands next to the printer and which
printing protocol it speaks. ``print_agents`` gains ``agent_version`` and
``protocol_version``, kept as the agent stated them. A row from before this
revision registered before the handshake carried anything, so both columns
stay nullable and read as "not stated".

Revision ID: 006_agent_versions
Revises: 005_timestamps_carry_their_zone
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '006_agent_versions'
down_revision: str | None = '005_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('print_agents', sa.Column('agent_version', sa.String(50), nullable=True))
    op.add_column('print_agents', sa.Column('protocol_version', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('print_agents', 'protocol_version')
    op.drop_column('print_agents', 'agent_version')
