"""add execution quantities to document lines

Revision ID: b47e41c0ad9a
Revises: f8baab5a52d7
Create Date: 2026-04-09 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b47e41c0ad9a'
down_revision: Union[str, None] = 'f8baab5a52d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_lines',
        sa.Column('expected_quantity', sa.Numeric(precision=12, scale=3), nullable=True),
    )
    op.add_column(
        'document_lines',
        sa.Column('done_quantity', sa.Numeric(precision=12, scale=3), nullable=True),
    )

    op.execute(
        """
        UPDATE document_lines AS line
        SET expected_quantity = line.quantity,
            done_quantity = CASE
                WHEN document.status IN ('CONFIRMED', 'COMPLETED') THEN line.quantity
                ELSE 0.000
            END
        FROM documents AS document
        WHERE document.id = line.document_id
        """
    )

    op.alter_column(
        'document_lines',
        'expected_quantity',
        existing_type=sa.Numeric(precision=12, scale=3),
        nullable=False,
    )
    op.alter_column(
        'document_lines',
        'done_quantity',
        existing_type=sa.Numeric(precision=12, scale=3),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column('document_lines', 'done_quantity')
    op.drop_column('document_lines', 'expected_quantity')