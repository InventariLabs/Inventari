"""rename food_and_health to nutrition in module references

Revision ID: 3fdf05c3e6d7
Revises: e78ca4d601ed
Create Date: 2026-05-09 22:06:41.094690

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fdf05c3e6d7'
down_revision: Union[str, None] = 'e78ca4d601ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET enabled_modules = (
            SELECT json_agg(
                CASE WHEN elem = 'food_and_health' THEN 'nutrition' ELSE elem END
            )
            FROM json_array_elements_text(enabled_modules) AS elem
        )
        WHERE enabled_modules::text LIKE '%%"food_and_health"%%'
        """
    )
    op.execute(
        """
        UPDATE module_installations
        SET module_name = 'nutrition'
        WHERE module_name = 'food_and_health'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET enabled_modules = (
            SELECT json_agg(
                CASE WHEN elem = 'nutrition' THEN 'food_and_health' ELSE elem END
            )
            FROM json_array_elements_text(enabled_modules) AS elem
        )
        WHERE enabled_modules::text LIKE '%%"nutrition"%%'
        """
    )
    op.execute(
        """
        UPDATE module_installations
        SET module_name = 'food_and_health'
        WHERE module_name = 'nutrition'
        """
    )
