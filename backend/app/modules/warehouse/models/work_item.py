"""What To do cannot derive: who a task is assigned to, and the boss's own tasks.

The tasks of the floor are read at request time from the documents, orders,
production runs and counts that ask for them, so their state follows what
happens to those records and is never typed in. Two things have no source to
read from, and this table holds them:

* the **assignee** of a derived task, keyed by the kind and id of its source;
* a **custom task** ("move the rack"), which is its own source: a title, an
  optional assignee and due date, and the moment it was ticked off.

A row for a derived task stays after its source is gone; it is harmless and
is simply never read again.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase

#: ``source_kind`` of a task the boss typed in.
CUSTOM_SOURCE_KIND = 'custom'


class WorkItemOverlay(CoreModelBase):
    """An assignee for a derived task, or a custom task of its own."""

    __tablename__ = 'document_work_item_overlays'
    __table_args__ = (
        Index(
            'uq_document_work_item_overlays_source',
            'organization_id',
            'source_kind',
            'source_id',
            unique=True,
            postgresql_where=text('source_id IS NOT NULL'),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    #: ``document``, ``purchase_order``, ``production_order``, ``cycle_count``
    #: or ``custom``.
    source_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    #: The record the task is derived from; empty for a custom task.
    source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    #: Custom tasks only.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
