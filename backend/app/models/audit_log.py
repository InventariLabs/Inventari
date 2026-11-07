import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.contracts._system_dtos import AuditAction, AuditTargetType
from app.database import Base

#: Re-exported beside the model, which is where the core services reach for
#: them. ``AuditTargetType`` was missing from this list while six of them
#: needed it, so each wrote its value out as a string instead.
__all__ = ['AuditAction', 'AuditLog', 'AuditTargetType']


class AuditLog(Base):
    __tablename__ = 'audit_log'
    __table_args__ = (
        Index('ix_audit_log_target', 'target_type', 'target_id'),
        # The journal's own sort order, id included. The page query is
        # ``WHERE organization_id = ? ORDER BY created_at DESC, id`` — neither
        # single-column index serves both halves, so Postgres either read the
        # organization and sorted it in memory, or walked the whole timeline
        # past every other organization's rows. The table is append-only by
        # trigger and nothing prunes it, so that wall only moves further
        # away. The id is last because the journal pages by the last entry
        # seen: a page that starts inside a batch written at one instant reads
        # the rest of it in id order, and that is a seek only when the index
        # ends in the id. DESC is written down, following the ledger's index —
        # the pattern this one is modelled on.
        Index(
            'ix_audit_log_org_created_at_id',
            'organization_id',
            text('created_at DESC'),
            'id',
        ),
        # The journal narrowed to one kind of thing. Three reads lean on it:
        # the page filtered by type walks this index in the page's own order
        # instead of the whole organization's timeline looking for matches
        # (a rare type meant reading most of it); the count under that filter
        # is an index-only scan instead of a sequential one; and the list of
        # types the screen offers is a loose scan with one index entry per
        # type, where DISTINCT read every row of the organization's journal on
        # each visit. What each of the table's indexes is for is written in
        # docs/subsystems/AUDIT.md.
        Index(
            'ix_audit_log_org_type_created_at',
            'organization_id',
            'target_type',
            text('created_at DESC'),
            'id',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # No index of its own: it leads both composites in ``__table_args__``.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID] = mapped_column()
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(500))
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text('now()'),
    )


# The immutability trigger used to be defined here and executed by a migration
# that imported it. It lives in the migration now
# (the core baseline migration), because a migration
# that reads today's model is not a snapshot of anything — and because the
# copy here outlived the only migration that ran it, so the constant said the
# rule was enforced while the database it described had no trigger at all.
