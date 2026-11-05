"""Durable email queue.

``EmailService`` async entry points enqueue a job row in production instead
of fire-and-forget SMTP from a thread pool. The scheduled worker claims due
jobs (FOR UPDATE SKIP LOCKED), sends OUTSIDE the row lock, and commits the
result per job. Failed sends retry with exponential backoff up to
``max_attempts``; crashed in-flight jobs (``sending`` with a stale
``claimed_at``) are reclaimed.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import run_sync_in_thread
from app.core.db_claim import due_or_zombie_clause
from app.core.db_utils import paginate_async
from app.core.logging import get_logger
from app.models.email_job import EmailJob
from app.services.crypto_service import decrypt_app_secret, encrypt_app_secret
from app.services.email_service import EmailService

logger = get_logger(__name__)

_STATUS_PENDING = 'pending'
_STATUS_SENDING = 'sending'
_STATUS_SENT = 'sent'
_STATUS_FAILED = 'failed'

_BATCH_LIMIT = 20
# Reclaim in-flight jobs whose claiming worker crashed mid-send.
_CLAIM_STALE_AFTER = timedelta(minutes=5)
# Backoff base: next attempt at now + BASE * 2**attempts (30s, 60s, 120s…).
_BACKOFF_BASE_SECONDS = 30
# Stands in when the sender refused without saying why — it never has, but a
# NULL here would read as "no failure" on the screen that lists failed mail.
_UNREPORTED_FAILURE = 'SMTP send failed without a reported reason'


async def enqueue_email_job(
    to_email: str,
    subject: str,
    html_content: str,
    smtp_config: dict[str, Any] | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    max_attempts: int = 5,
    organization_id: uuid.UUID | None = None,
    failure_notice: dict[str, str] | None = None,
) -> uuid.UUID | None:
    """Persist an email job in its own short transaction. Returns the job id.

    Failures are logged and swallowed (returns None): email must never break
    the calling business flow — same contract as the old fire-and-forget.
    """
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        logger.warning('[email-jobs] AsyncSessionLocal unavailable; email dropped')
        return None

    smtp_config_enc = (
        encrypt_app_secret(json.dumps(smtp_config)) if smtp_config is not None else None
    )
    failure_notice_enc = (
        encrypt_app_secret(json.dumps(failure_notice))
        if failure_notice is not None
        else None
    )
    try:
        async with db_facade.AsyncSessionLocal() as db:
            job = EmailJob(
                organization_id=organization_id,
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                attachment_bytes=attachment_bytes,
                attachment_filename=attachment_filename,
                smtp_config_enc=smtp_config_enc,
                failure_notice_enc=failure_notice_enc,
                max_attempts=max_attempts,
            )
            db.add(job)
            await db.commit()
            return job.id  # type: ignore[no-any-return]
    except Exception:  # email enqueue must never break the caller
        logger.exception('[email-jobs] Failed to enqueue email to %s', to_email)
        return None


async def list_failed_jobs_async(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[EmailJob], int]:
    """The organization's mail that exhausted its retries, newest first.

    The queue gives up after ``max_attempts`` and marks the row ``failed``;
    until this read existed, that row was the end of the message's life for
    everyone except a reader of the container log. Scoped to one tenant:
    the addresses and subjects here are the organization's own.
    """
    stmt = (
        select(EmailJob)
        .where(
            EmailJob.organization_id == organization_id,
            EmailJob.status == _STATUS_FAILED,
        )
        .order_by(EmailJob.created_at.desc(), EmailJob.id)
    )
    return await paginate_async(db, stmt, limit=limit, offset=offset)


def _decode_smtp_config(job: EmailJob) -> dict[str, Any] | None:
    if not job.smtp_config_enc:
        return None
    try:
        result = json.loads(decrypt_app_secret(job.smtp_config_enc))
        return result if isinstance(result, dict) else None
    except Exception:  # noqa: BLE001 — corrupt blob must not kill the worker
        logger.error('[email-jobs] Cannot decrypt smtp_config for job %s', job.id)
        return None


def _decode_failure_notice(job: EmailJob) -> dict[str, str] | None:
    if not job.failure_notice_enc:
        return None
    try:
        result = json.loads(decrypt_app_secret(job.failure_notice_enc))
    except ValueError:  # includes UndecryptableSecretError and bad JSON
        logger.error('[email-jobs] Cannot read failure notice for job %s', job.id)
        return None
    if not isinstance(result, dict) or not result.get('user_id'):
        return None
    return {key: str(value) for key, value in result.items()}


async def _tell_the_sender(db: AsyncSession, notice: dict[str, str]) -> None:
    """Turn a failed job's notice into one in-app notification.

    The row commits with the job's failure; it is not pushed over the socket
    (a service does not go through the core facade), so it shows on the
    administrator's next notification poll.
    """
    from app.services.notification_service import notification_service

    await notification_service.create_notification_async(
        db,
        uuid.UUID(notice['user_id']),
        notice.get('title', ''),
        notice.get('content', ''),
        type='error',
        link=notice.get('link'),
    )


async def _claim_batch(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Claim due jobs in one short transaction (locks released at commit)."""
    zombie_cutoff = now - _CLAIM_STALE_AFTER
    stmt = (
        select(EmailJob)
        .where(
            due_or_zombie_clause(
                status_col=EmailJob.status,
                pending_status=_STATUS_PENDING,
                inflight_status=_STATUS_SENDING,
                due_at_col=EmailJob.next_attempt_at,
                claimed_col=EmailJob.claimed_at,
                now=now,
                zombie_cutoff=zombie_cutoff,
            )
        )
        .order_by(EmailJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(_BATCH_LIMIT)
    )
    rows = (await db.execute(stmt)).scalars().all()
    claimed: list[uuid.UUID] = []
    for row in rows:
        row.status = _STATUS_SENDING
        row.claimed_at = now
        row.attempts += 1
        claimed.append(row.id)
    await db.commit()
    return claimed


async def _send_job(db: AsyncSession, job_id: uuid.UUID, now: datetime) -> None:
    """Send one claimed job OUTSIDE any row lock; commit the result."""
    job = await db.get(EmailJob, job_id)
    if job is None or job.status != _STATUS_SENDING:
        return

    smtp_config = _decode_smtp_config(job)
    if job.attachment_bytes is not None and job.attachment_filename:
        result = await run_sync_in_thread(
            lambda: EmailService._send_email_with_attachment(
                job.to_email,
                job.subject,
                job.html_content,
                job.attachment_bytes,  # type: ignore[arg-type]
                job.attachment_filename,  # type: ignore[arg-type]
                smtp_config,
            )
        )
    else:
        result = await run_sync_in_thread(
            lambda: EmailService.deliver(
                job.to_email, job.subject, job.html_content, smtp_config=smtp_config
            )
        )

    if result.ok:
        job.status = _STATUS_SENT
        job.sent_at = now
        job.last_error = None
    else:
        # What stopped the mail, not what the queue did about it. The row
        # used to record 'max attempts reached' and 'smtp send returned
        # False' — both true, neither actionable: a wrong relay password, a
        # closed port and a host that never answered all read the same, and
        # the row is the only place an administrator meets any of them.
        job.last_error = result.error or _UNREPORTED_FAILURE
        if job.attempts >= job.max_attempts:
            job.status = _STATUS_FAILED
            notice = _decode_failure_notice(job)
            if notice is not None:
                await _tell_the_sender(db, notice)
            logger.error(
                '[email-jobs] Job %s to %s FAILED after %d attempts: %s',
                job.id,
                job.to_email,
                job.attempts,
                job.last_error,
            )
        else:
            job.status = _STATUS_PENDING
            job.next_attempt_at = now + timedelta(
                seconds=_BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
            )
    await db.commit()


async def process_email_jobs_batch(db: AsyncSession) -> int:
    """Claim + send one batch. Returns the number of jobs sent."""
    now = datetime.now(UTC)
    claimed = await _claim_batch(db, now)
    sent = 0
    for job_id in claimed:
        job_before = await db.get(EmailJob, job_id)
        try:
            await _send_job(db, job_id, now)
        except Exception:  # one bad job must not kill the batch
            logger.exception('[email-jobs] Send crashed for job %s', job_id)
            await db.rollback()
            continue
        job_after = await db.get(EmailJob, job_id)
        if (
            job_before is not None
            and job_after is not None
            and job_after.status == _STATUS_SENT
        ):
            sent += 1
    return sent


async def run_email_jobs_once() -> None:
    """Scheduled-task entry point: open a session and process one batch."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        return
    async with db_facade.AsyncSessionLocal() as db:
        try:
            sent = await process_email_jobs_batch(db)
            if sent:
                logger.info('[email-jobs] Sent %d queued email(s)', sent)
        except Exception:  # worker loop must never crash
            logger.exception('[email-jobs] Batch failed')
            await db.rollback()
