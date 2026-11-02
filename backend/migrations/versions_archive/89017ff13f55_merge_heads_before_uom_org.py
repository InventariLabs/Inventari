"""merge heads before uom org

Revision ID: 89017ff13f55
Revises: 7031d8273a07, add_tax_rate_to_po_lines
Create Date: 2026-04-22 11:29:04.112058

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89017ff13f55'
down_revision: Union[str, None] = ('7031d8273a07', 'add_tax_rate_to_po_lines')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
