"""the document links point at warehouse: rewrite the stored notification links

Revision ID: docurl01
Revises: modkey01
Create Date: 2026-10-22

The warehouse module's screens moved from ``/documents`` to ``/warehouse``
before the first release, and the document detail from ``/documents/{id}``
to ``/warehouse/documents/{id}``. A notification is the one place where the
old address survives the deploy: its ``link`` is written when the notification
is created, not when it is read, so a row stored yesterday still points at a
screen the new build no longer serves.

The sweep found two writers, and both store a document detail address: the
receipt a purchase order creates (``/documents/{receipt_id}``) and the
rejection notice an approver's decision sends back to the requester
(``/documents/{doc_id}``). Work items build their links when they are read,
so they need no rewrite. Every row matching the old document prefix is
carried across; a link to a module screen (none is written today) would need
the module prefix instead of the document noun, which is why the migration
does not guess a bare prefix swap.

The downgrade puts the old address back, so a rollback lands on a build that
serves it again.

A data migration of its own, with no schema change, written as plain SQL so
that it also renders offline (``alembic upgrade --sql``).
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'docurl01'
down_revision: str | None = 'modkey01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = '/documents'
_NEW = '/warehouse/documents'


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE notifications
        SET link = '{_NEW}' || substring(link from {len(_OLD) + 1})
        WHERE link LIKE '{_OLD}/%'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE notifications
        SET link = '{_OLD}' || substring(link from {len(_NEW) + 1})
        WHERE link LIKE '{_NEW}/%'
        """
    )
