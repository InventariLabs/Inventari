import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ItemExportJob(Base):
    """A spreadsheet export that outgrew one request, and how far it has got.

    The sheet of every record of a hundred thousand products takes minutes to
    write, longer than a phone or a proxy waits on one request. The endpoint
    answers with this row instead, the workbook is written in the background
    and stored at ``file_path``, and the screen reads ``processed`` of
    ``total`` until ``status`` leaves ``running``; then it fetches the file.

    ``updated_at`` moves with every report of progress. A job that is still
    ``running`` long after it last moved belongs to a worker that is gone;
    the status read says so
    (:func:`app.services.items._export_job.read_job_async`). A job and its
    file are deleted a day after the job started, by the daily table
    retention (:mod:`app.services.table_retention`).
    """

    __tablename__ = 'item_export_jobs'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE')
    )
    # "running" | "done" | "failed"
    status: Mapped[str] = mapped_column(String(20), default='running')
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
