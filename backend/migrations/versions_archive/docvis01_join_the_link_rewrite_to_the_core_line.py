"""join the document link rewrite to the core line that grew beside it

Revision ID: docvis01
Revises: docurl01, poolcode01
Create Date: 2026-10-23

``docurl01`` (stored notification links follow the warehouse module to
``/warehouse``) was written on top of ``modkey01`` while the core line went on
through ``visperm01`` (role permissions), ``imgkey01`` (image columns keep the
storage key), ``legacyvals01`` (pre-release legacy values and columns
leave) and ``poolcode01`` (a pool label holds any location code).
``docurl01`` touches only ``notifications.link``, which none of those
reads or writes, so the order between the two sides does not matter; this
revision only joins the two heads so that ``alembic upgrade head`` has one
target again.
"""

from collections.abc import Sequence

revision: str = 'docvis01'
down_revision: str | Sequence[str] | None = ('docurl01', 'poolcode01')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
