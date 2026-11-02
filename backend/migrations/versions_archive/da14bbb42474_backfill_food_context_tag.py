"""backfill context_tag food on expiry/freezing locations

Revision ID: da14bbb42474
Revises: c7c3360e93f1
Create Date: 2026-03-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'da14bbb42474'
down_revision: Union[str, None] = 'c7c3360e93f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE storage_locations "
        "SET context_tag = 'food' "
        "WHERE behavior_mode IN ('EXPIRY', 'FREEZING') "
        "AND context_tag IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE storage_locations "
        "SET context_tag = NULL "
        "WHERE context_tag = 'food'"
    )
