import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ItemImportJob(Base):
    """A spreadsheet import that outgrew one request, and what it has done so far.

    A sheet of thousands of rows takes minutes — each row goes through the
    same door as the form — and no browser or proxy waits that long on one
    request. The endpoint answers with this row instead, the import runs on
    in the background, and the screen reads ``processed`` of ``total`` until
    ``status`` leaves ``running``. The finished import's answer is stored
    whole in ``result``.

    ``updated_at`` moves with every committed batch. A job that is still
    ``running`` long after it last moved belongs to a worker that is gone;
    the status read says so (:func:`app.services.items._import_job.read_job_async`).
    """

    __tablename__ = 'item_import_jobs'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    filename: Mapped[str] = mapped_column(String(255))
    # "running" | "done" | "failed"
    status: Mapped[str] = mapped_column(String(20), default='running')
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
