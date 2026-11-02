import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class EmailJob(Base):
    """Durable outbound email queue.

    ``EmailService`` async entry points enqueue a row instead of doing
    fire-and-forget SMTP from a thread pool. The email-jobs worker claims
    rows (FOR UPDATE SKIP LOCKED), sends outside the lock, and retries with
    backoff up to ``max_attempts`` before marking the job ``failed``.

    ``smtp_config_enc`` holds the per-call SMTP override as a Fernet-
    encrypted JSON blob (it can contain credentials — never store it plain).
    """

    __tablename__ = 'email_jobs'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The tenant whose administrator answers for this message. Every account
    # here belongs to an organization — registration mints one when no
    # invitation names it — so every mail this tree queues carries one too,
    # password resets and registration links included. It is what makes a job
    # that exhausted its retries reachable from a screen instead of only from
    # the container log. Nullable for rows queued before that was true and for
    # an out-of-tree module calling the facade without it.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    html_content: Mapped[str] = mapped_column(Text)
    attachment_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    attachment_filename: Mapped[str | None] = mapped_column(String(255))
    smtp_config_enc: Mapped[str | None] = mapped_column(Text)
    # What to tell one user if this mail gives up: a Fernet-encrypted JSON
    # ``{user_id, title, content, link}``, encrypted because the content may
    # carry the very link the mail was meant to deliver. Set by the caller that
    # needs the message to be answered for (an approved registration link),
    # read once, when the row is marked ``failed``.
    failure_notice_enc: Mapped[str | None] = mapped_column(Text)

    # "pending" | "sending" | "sent" | "failed"
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
