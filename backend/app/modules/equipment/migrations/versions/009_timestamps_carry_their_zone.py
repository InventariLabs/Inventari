"""timestamps carry their zone: convert the naive equipment columns to timestamptz

Revision ID: 009_timestamps_carry_their_zone
Revises: 008_drop_module_doc_templates
Create Date: 2026-10-10

A database that grew through the migration chain before it was flattened
holds many timestamp columns as ``timestamp without time zone`` while the
models declare ``DateTime(timezone=True)``: the API then sends those times
without an offset and the browser shows them shifted by the reader's UTC
offset, and a Python comparison against an aware ``now`` raises
``TypeError``. The core chain's ``tzaware01`` explains it in full; this
revision converts this module's tables. Stored values are read as UTC; a
column that is already aware is left alone, so a database built from the
current chain sees no change.

Downgrade leaves the columns aware.
"""

from collections.abc import Sequence

from app.core.migration_helpers import convert_naive_timestamps_to_utc

revision: str = '009_timestamps_carry_their_zone'
down_revision: str | None = '008_drop_module_doc_templates'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every column the models declare ``DateTime(timezone=True)``, frozen as of
#: this revision.
_AWARE_COLUMNS: dict[str, tuple[str, ...]] = {
    'audit_campaigns': (
        'launched_at',
        'deadline',
        'last_reminder_sent_at',
        'created_at',
        'updated_at',
    ),
    'audit_response_items': ('created_at',),
    'audit_responses': (
        'token_expires_at',
        'responded_at',
        'email_sent_at',
        'reminder_sent_at',
        'created_at',
    ),
    'equipment_assignments': (
        'checked_out_at',
        'expected_return_at',
        'checked_in_at',
        'created_at',
    ),
    'equipment_attachments': ('created_at',),
    'equipment_maintenance_logs': ('created_at', 'updated_at'),
}


def upgrade() -> None:
    convert_naive_timestamps_to_utc(_AWARE_COLUMNS)


def downgrade() -> None:
    # Nothing to restore: the naive type was the defect, and on a database
    # that was aware all along there is nothing to undo. Turning the columns
    # back would bring the shifted times back with them.
    pass
