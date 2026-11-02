"""The print queue: the printers an organization has, and what they print.

A print agent runs next to a printer, outside the server's reach, and asks
the server for work — the server never calls it. So the queue is two tables:
the agents that have announced themselves (and when they last asked), and the
jobs waiting for, being printed by, or finished by one of them.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base

#: A double, spelled as Postgres reads it back: a bare ``Float`` has no
#: precision and the migrated ``double precision`` column has 53 bits.
_DOUBLE = Float(precision=53)


class PrintAgent(Base):
    """A printer, as its local agent announced it."""

    __tablename__ = 'print_agents'
    __table_args__ = (
        UniqueConstraint('organization_id', 'name', name='uq_print_agents_org_name'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    #: Chosen on the agent's machine ("office", "garage"); the agent registers
    #: under it again on every start, which is how a restart finds its jobs.
    name: Mapped[str] = mapped_column(String(100))
    #: What the agent says it drives (``brother-p710bt``, ``cups``…). Only
    #: shown: the server draws one label file for every printer, and fitting
    #: it to this one is the agent's job.
    printer_type: Mapped[str] = mapped_column(String(50))
    #: What the agent said about itself at registration: its own release, and
    #: the printing protocol it speaks. Kept so an installation can tell an
    #: old agent from a new one; an agent that predates the handshake is
    #: refused and never gets a row here.
    agent_version: Mapped[str | None] = mapped_column(String(50))
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrintJob(Base):
    """Labels sent to one printer, and how that went."""

    __tablename__ = 'print_jobs'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('print_agents.id', ondelete='CASCADE'), index=True
    )
    #: ``queued`` → ``printing`` (claimed, under a lease) → ``printed`` or
    #: ``failed``. A lease that runs out puts the job back in line.
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    #: What to print, frozen when the job was queued: one entry per label with
    #: its ``short_code``, ``caption``, ``qr_only`` and, for a pool label, its
    #: ``label_id`` — the ones marked printed when the agent reports success.
    labels: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    #: The reads, any one of which lets a caller see this job in the queue or
    #: send it again — those of the screens that may send its kind of label
    #: (``items:read`` for a product's; ``items:read`` and ``equipment:read``
    #: for pool labels; ``locations:read`` and ``warehouse:read`` for
    #: shelves; the queueing module's own read for a label it drew). The
    #: labels keep what their records said.
    read_permissions: Mapped[list[str]] = mapped_column(JSONB)
    #: The size of every label in the job — the one the person previewed, or
    #: the app's default where nothing was previewed. Kept as given, to the
    #: last digit: a size rounded on the way in (50.06 stored as 50.1) draws
    #: a label a pixel wider than the preview it was sent from.
    width_mm: Mapped[float] = mapped_column(_DOUBLE, server_default='50.0')
    height_mm: Mapped[float] = mapped_column(_DOUBLE, server_default='24.0')
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    #: The share of their size the agent printed the labels at, when its
    #: printer could not hold them whole; None when they printed at their size.
    scale: Mapped[float | None] = mapped_column(_DOUBLE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
