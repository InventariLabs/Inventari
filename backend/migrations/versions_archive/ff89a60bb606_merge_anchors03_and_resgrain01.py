"""merge anchors03 and resgrain01

Revision ID: ff89a60bb606
Revises: anchors03, resgrain01
Create Date: 2026-09-28

The records' anchor key is validated by ``anchors03`` and a reservation names
its own grain since ``resgrain01``; both hang off ``anchors01``, so a database
that takes both needs one revision joining them. Nothing to run: each side
already did its work.
"""

revision = 'ff89a60bb606'
down_revision = ('anchors03', 'resgrain01')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
