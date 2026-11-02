"""timestamps carry their zone: convert the naive core columns to timestamptz

Revision ID: tzaware01
Revises: emailnotice01
Create Date: 2026-10-10

A database that grew through the migration chain before it was flattened
into ``baseline_001`` holds many of its timestamp columns as ``timestamp
without time zone``, while the models and every migration since declare
``DateTime(timezone=True)``; no revision ever converted them, so such an
installation stayed naive for good (measured on one: 83 naive columns, against
none on a database built from today's chain). Two things follow. The driver
hands those values back without a zone, so the API sends them without an
offset and the browser reads a UTC time as local — a document's creation
time shows two hours away from its approval request, written in the same
transaction. And a Python comparison against an aware ``now`` raises
``TypeError`` (an account lockout check, for one).

This revision converts the core tables' columns; each module converts its own
in a revision of its own chain. The stored values are what the application
wrote, in UTC, and are read as such. A column that is already aware, or a
table that is not there, is left alone, so on a database built from the
current chain this does nothing.

Downgrade leaves the columns aware.
"""

from collections.abc import Sequence

from app.core.migration_helpers import convert_naive_timestamps_to_utc

revision: str = 'tzaware01'
down_revision: str | None = 'emailnotice01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every column the models declare ``DateTime(timezone=True)``, frozen as of
#: this revision.
_AWARE_COLUMNS: dict[str, tuple[str, ...]] = {
    'ai_connections': ('created_at', 'updated_at'),
    'ai_usage_logs': ('created_at',),
    'announcements': ('active_from', 'active_until', 'created_at'),
    'audit_log': ('created_at',),
    'document_templates': ('created_at', 'updated_at'),
    'email_jobs': ('next_attempt_at', 'claimed_at', 'created_at', 'sent_at'),
    'event_deliveries': ('next_attempt_at', 'created_at', 'updated_at'),
    'event_outbox': ('created_at', 'published_at'),
    'item_attachments': ('created_at',),
    'item_history': ('created_at',),
    'item_type_definitions': ('created_at', 'updated_at'),
    'items': ('deleted_at', 'created_at', 'updated_at'),
    'label_pool': ('assigned_at', 'created_at', 'printed_at', 'last_scanned_at'),
    'module_installations': ('installed_at', 'updated_at'),
    'notifications': ('created_at',),
    'organization_invitations': ('created_at', 'expires_at', 'used_at', 'revoked_at'),
    'organizations': ('created_at',),
    'partners': ('created_at', 'updated_at'),
    'product_templates': ('created_at', 'updated_at'),
    'registration_requests': ('created_at', 'expires_at', 'accepted_at', 'rejected_at'),
    'roles': ('created_at',),
    'stock_anchors': ('created_at',),
    'stock_lots': ('created_at',),
    'stock_moves': ('created_at', 'updated_at', 'completed_at'),
    'stock_reservations': ('created_at',),
    'stock_valuation_layers': ('created_at',),
    'storage_locations': ('created_at',),
    'system_settings': ('updated_at',),
    'users': ('created_at', 'updated_at', 'blocked_at', 'locked_until'),
}


def upgrade() -> None:
    convert_naive_timestamps_to_utc(_AWARE_COLUMNS)


def downgrade() -> None:
    # Nothing to restore: the naive type was the defect, and on a database
    # that was aware all along there is nothing to undo. Turning the columns
    # back would bring the shifted times back with them.
    pass
