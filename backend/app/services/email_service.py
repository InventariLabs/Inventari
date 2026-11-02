import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import StrEnum
from typing import Any
from uuid import UUID

import markupsafe

from app.config import settings
from app.core.async_utils import run_sync_in_thread
from app.core.db_retry import mark_external_effect
from app.core.logging import get_logger
from app.i18n import (
    get_invitation_email_content,
    get_password_reset_email_content,
    get_registration_email_content,
)

logger = get_logger(__name__)


#: How long a connection attempt may hang before the caller gets an answer.
#: Without it an unreachable host held a request for the system TCP limit —
#: 134 seconds measured in the walkthrough — and the user saw a spinner.
SMTP_TIMEOUT_SECONDS = 15


class SmtpEncryption(StrEnum):
    """Transport security, chosen explicitly rather than guessed from a port."""

    NONE = 'none'
    STARTTLS = 'starttls'
    SSL = 'ssl'


def _encryption_implied_by_port(port: int) -> SmtpEncryption:
    """Read the intent of a configuration stored before the field existed.

    New configurations always carry ``encryption``; this only interprets old
    ones, and it interprets 465 the way the rest of the world does — as
    implicit TLS, not as plaintext, which is what the previous code did.
    """
    if port == 465:
        return SmtpEncryption.SSL
    if port == 587:
        return SmtpEncryption.STARTTLS
    return SmtpEncryption.NONE


@dataclass(frozen=True)
class SMTPConfig:
    """Resolved SMTP configuration (per-call override or system default)."""

    host: str | None
    port: int
    user: str | None
    password: str | None
    from_email: str | None
    from_name: str | None
    encryption: SmtpEncryption

    @property
    def problem(self) -> str | None:
        """Why a message cannot leave with this configuration, or None.

        An unauthenticated relay — a company-internal one, MailHog, a local
        postfix — has neither a username nor a password and sends. Only one
        of the two is a mistake: the server would be offered half a login.
        """
        if not self.host:
            return 'SMTP is not configured'
        if bool(self.user) != bool(self.password):
            return (
                'SMTP username and password must both be set, or both left empty '
                'for a relay that does not ask for a login'
            )
        return None

    @property
    def is_configured(self) -> bool:
        return self.problem is None


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Whether the message left, and — when it did not — what stopped it."""

    ok: bool
    error: str | None = None


def _resolve_smtp_config(smtp_config: dict[str, Any] | None) -> SMTPConfig:
    """Resolve SMTP config: per-call override → system settings → defaults.

    On a demo the override is dropped rather than merged. Visitors there are
    the organization's administrators, so a stored — or just typed — host
    would let them open connections from our address to any machine and port
    they name, and every message sent that way would bypass the Mailpit
    inbox the demo captures mail in. The system settings still apply, because
    the demo stack pins them to that same inbox.
    """
    cfg = {} if settings.INVENTARI_DEMO else (smtp_config or {})
    port = cfg.get('port') or settings.SMTP_PORT or 587
    stored = cfg.get('encryption') or settings.SMTP_ENCRYPTION
    # A server named in the override brings its own login, or none: the
    # installation's credentials belong to the installation's server and must
    # not be offered to a host an administrator typed.
    own_server = bool(cfg.get('host'))
    return SMTPConfig(
        host=cfg.get('host') or settings.SMTP_HOST,
        port=port,
        user=cfg.get('user') or (None if own_server else settings.SMTP_USER),
        password=cfg.get('password')
        or (None if own_server else settings.SMTP_PASSWORD),
        from_email=cfg.get('from_email') or settings.EMAILS_FROM_EMAIL,
        from_name=cfg.get('from_name') or settings.EMAILS_FROM_NAME,
        encryption=SmtpEncryption(stored)
        if stored
        else _encryption_implied_by_port(port),
    )


def warn_if_system_smtp_is_plaintext() -> bool:
    """Log a warning when the deployment's own SMTP relay carries no TLS.

    An SMTP port that is neither 587 nor 465, with no explicit
    ``SMTP_ENCRYPTION``, resolves to plaintext — and then the relay password
    and every invitation and password-reset link travel the wire in the
    clear. That is a legitimate setup for a relay on localhost and a bad
    surprise for anything else, and nothing said which one this was.

    Returns whether it warned, so a test can assert on the decision rather
    than on the log line.
    """
    if not settings.SMTP_HOST:
        return False

    cfg = _resolve_smtp_config(None)
    if cfg.encryption is not SmtpEncryption.NONE:
        return False

    logger.warning(
        'SMTP is configured without TLS (host=%s port=%s): the relay password '
        'and every invitation and reset link cross the network in the clear. '
        'Set SMTP_ENCRYPTION=starttls (587) or ssl (465), or leave it as it is '
        'if the relay is on this host.',
        cfg.host,
        cfg.port,
    )
    return True


def _connect(cfg: SMTPConfig) -> smtplib.SMTP:
    """Open the connection the configuration asked for, with a time limit."""
    assert cfg.host is not None
    if cfg.encryption is SmtpEncryption.SSL:
        return smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS)
    return smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS)


def _send_message(cfg: SMTPConfig, msg: MIMEMultipart) -> None:
    """Hand a built message to the server the configuration names.

    One transport for every message, attachment or not. The attachment path
    used to open a plain ``smtplib.SMTP`` of its own, with no timeout and
    with STARTTLS decided by the port being exactly 587 — so an
    organization on SSL/465 could receive a notification and never the
    protocol attached to it, and an unreachable host held the worker for
    the system TCP limit instead of fifteen seconds.
    """
    with _connect(cfg) as server:
        if cfg.encryption is SmtpEncryption.STARTTLS:
            server.starttls()
        if cfg.user and cfg.password:
            server.login(cfg.user, cfg.password)
        server.send_message(msg)


#: The card every transactional email arrives in. It was written out four
#: times — registration, invitation, password reset, and the equipment
#: attestation in its own module — and the copies had already begun to
#: differ in whitespace and in which paragraphs they carried, which is how
#: one of them would eventually be restyled alone.
_SHELL = """<html>
    <body style="font-family: sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
            <h2 style="color: #2563eb;">{heading}</h2>
{body}
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #999;">{footer}</p>
        </div>
    </body>
</html>"""


def email_shell(heading: str, body_html: str, footer: str) -> str:
    """One card around every transactional email.

    *body_html* is inserted as it is: it is markup the caller built, not
    text a user typed. Anything that came from a person has to be escaped
    before it gets here — see the attestation mail, which escapes the
    administrator's own message.
    """
    return _SHELL.format(heading=heading, body=body_html, footer=footer)


def email_button(url: str, label: str) -> str:
    """The one call to action, centred, as every one of these mails has it."""
    return (
        '            <div style="text-align: center; margin: 30px 0;">\n'
        f'                <a href="{url}" style="background-color: #2563eb; '
        'color: white; padding: 12px 25px; text-decoration: none; '
        f'border-radius: 8px; font-weight: bold;">{label}</a>\n'
        '            </div>'
    )


def email_fallback_link(intro: str, url: str) -> str:
    """The address spelled out, for a client that does not render the button."""
    return (
        f'            <p style="font-size: 12px; color: #666;">{intro}<br>\n'
        f'            <a href="{url}">{url}</a></p>'
    )


class EmailService:
    @staticmethod
    def is_configured(smtp_config: dict | None = None) -> bool:
        """Whether a message sent with this configuration could leave at all."""
        return _resolve_smtp_config(smtp_config).is_configured

    @staticmethod
    def deliver(
        to_email: str, subject: str, html_content: str, smtp_config: dict | None = None
    ) -> EmailDeliveryResult:
        """Send an HTML email and report what happened.

        Callers that only need to know whether it worked use ``send_email``;
        the test-email endpoint uses this one, because "it failed" is not an
        answer an administrator can act on.
        """

        cfg = _resolve_smtp_config(smtp_config)

        if cfg.problem:
            logger.warning('%s. Email NOT sent.', cfg.problem)
            return EmailDeliveryResult(ok=False, error=cfg.problem)

        assert cfg.host is not None
        try:
            msg = MIMEMultipart()
            msg['From'] = f'{cfg.from_name} <{cfg.from_email}>'
            msg['To'] = to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(html_content, 'html'))

            _send_message(cfg, msg)

            logger.info(f'Email sent successfully to {to_email}')
            return EmailDeliveryResult(ok=True)
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f'Failed to send email to {to_email}: {e}')
            return EmailDeliveryResult(ok=False, error=str(e))

    @staticmethod
    def send_email(
        to_email: str, subject: str, html_content: str, smtp_config: dict | None = None
    ) -> bool:
        """Sends an HTML email using provided or default SMTP settings."""
        return EmailService.deliver(
            to_email, subject, html_content, smtp_config=smtp_config
        ).ok

    @staticmethod
    async def send_registration_link_async(
        to_email: str,
        registration_link: str,
        lang: str = 'en',
        smtp_config: dict | None = None,
        organization_id: UUID | None = None,
        failure_notice: dict[str, str] | None = None,
    ) -> bool:
        """Render and queue the registration email.

        Rides the durable ``email_jobs`` queue in production: an SMTP
        outage leaves the job retrying instead of silently dropping the
        link a new account is waiting on. TESTING keeps the direct send
        so tests can assert delivery synchronously.
        """
        full_url = f'{settings.FRONTEND_URL.rstrip("/")}{registration_link}'

        t = get_registration_email_content(lang)

        html = email_shell(
            t['greeting'],
            f'            <p>{t["body"]}</p>\n            <p>{t["action"]}</p>\n'
            + email_button(full_url, t['button'])
            + '\n'
            + email_fallback_link(t['footer'], full_url),
            t['auto_gen'],
        )
        return await EmailService.send_email_async(
            to_email,
            t['subject'],
            html,
            smtp_config=smtp_config,
            organization_id=organization_id,
            failure_notice=failure_notice,
        )

    @staticmethod
    async def send_invitation_async(
        to_email: str,
        join_link: str,
        organization_name: str,
        role: str,
        lang: str = 'en',
        smtp_config: dict | None = None,
        organization_id: UUID | None = None,
    ) -> bool:
        """Render and queue the organization-invitation email.

        *role* is either a built-in level, which the template translates, or
        the name of an org-scoped custom role, which is used as it was typed —
        a name the organization chose has no translation to look up.

        Queued in production like every other mail, so an SMTP outage
        retries instead of stranding an invitee behind a silent loss.
        """
        full_url = f'{settings.FRONTEND_URL.rstrip("/")}{join_link}'

        t = get_invitation_email_content(lang)
        role_label = t['roles'].get(role, role)

        # Both values are typed by an admin and land in someone else's mail
        # client: the organization's name, and a custom role's name, which is
        # used as it was typed because a name the organization chose has no
        # translation to look up. Escaped like the attestation mail next door.
        safe_org = markupsafe.escape(organization_name)
        safe_role = markupsafe.escape(role_label)

        html = email_shell(
            t['greeting'],
            f'            <p>{t["body"].format(organization=safe_org)}</p>\n'
            f'            <p>{t["role_line"].format(role=safe_role)}</p>\n'
            f'            <p>{t["action"]}</p>\n'
            + email_button(full_url, t['button'])
            + '\n'
            + email_fallback_link(t['footer'], full_url)
            + f'\n            <p style="font-size: 12px; color: #666;">{t["expiry"]}</p>',
            t['auto_gen'],
        )
        subject = t['subject'].format(organization=organization_name)

        return await EmailService.send_email_async(
            to_email,
            subject,
            html,
            smtp_config=smtp_config,
            organization_id=organization_id,
        )

    @staticmethod
    async def send_password_reset_email_async(
        to_email: str,
        reset_link: str,
        lang: str = 'en',
        smtp_config: dict | None = None,
        organization_id: UUID | None = None,
    ) -> bool:
        """Render and queue the password-reset email.

        The one mail whose loss locks a user out entirely, so it rides
        the durable queue in production like the rest. TESTING keeps the
        direct send.
        """
        full_url = f'{settings.FRONTEND_URL.rstrip("/")}{reset_link}'

        t = get_password_reset_email_content(lang)

        html = email_shell(
            t['greeting'],
            f'            <p>{t["body"]}</p>\n            <p>{t["action"]}</p>\n'
            + email_button(full_url, t['button'])
            + '\n'
            + email_fallback_link(t['footer'], full_url)
            + f'\n            <p style="font-size: 12px; color: #b91c1c;">{t["expiry"]}</p>',
            t['auto_gen'],
        )

        return await EmailService.send_email_async(
            to_email,
            t['subject'],
            html,
            smtp_config=smtp_config,
            organization_id=organization_id,
        )

    # ── async wrappers (avoids blocking the event loop) ──────────────────

    @staticmethod
    def _send_email_with_attachment(
        to_email: str,
        subject: str,
        html_content: str,
        attachment_bytes: bytes,
        attachment_filename: str,
        smtp_config: dict | None = None,
    ) -> EmailDeliveryResult:
        """Send HTML email with binary attachment (sync, real SMTP I/O).

        Private on purpose: public callers go through
        ``send_email_with_attachment_async`` (queue) — only the email-jobs
        worker and the TESTING fast-path call this directly (avoids a
        sync/async twin pair in the architecture linter).

        Reports what stopped it, like ``deliver``: the queue writes the
        reason onto the job row, and "it failed" is not a reason an
        administrator can act on.
        """
        from email import encoders
        from email.mime.base import MIMEBase

        cfg = _resolve_smtp_config(smtp_config)
        if cfg.problem:
            logger.warning('%s. Email NOT sent.', cfg.problem)
            return EmailDeliveryResult(ok=False, error=cfg.problem)
        assert cfg.host is not None
        try:
            msg = MIMEMultipart()
            msg['From'] = f'{cfg.from_name} <{cfg.from_email}>'
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(html_content, 'html'))
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{attachment_filename}"',
            )
            msg.attach(part)
            _send_message(cfg, msg)
            logger.info(f'Email with attachment sent to {to_email}')
            return EmailDeliveryResult(ok=True)
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f'Failed to send email with attachment to {to_email}: {e}')
            return EmailDeliveryResult(ok=False, error=str(e))

    @staticmethod
    async def send_email_async(
        to_email: str,
        subject: str,
        html_content: str,
        smtp_config: dict | None = None,
        organization_id: UUID | None = None,
        failure_notice: dict[str, str] | None = None,
    ) -> bool:
        """Queue the email for durable delivery.

        Production: enqueues an ``email_jobs`` row (worker sends with retry);
        returns True once accepted. TESTING: keeps the legacy behavior —
        real SMTP send offloaded to a thread — so tests can assert delivery
        synchronously. ``organization_id`` is optional tenant tagging for
        queue filtering/audit.
        """
        # Both paths below leave a trace the request's rollback cannot undo:
        # TESTING sends for real, production commits the job row in the
        # queue's own short transaction — a retried request would enqueue a
        # second, identical email. Either way the request is no longer safe
        # to repeat.
        mark_external_effect('email:queued')
        if settings.TESTING:
            return await run_sync_in_thread(
                lambda: EmailService.send_email(
                    to_email, subject, html_content, smtp_config
                )
            )
        from app.services.email_jobs import enqueue_email_job

        job_id = await enqueue_email_job(
            to_email,
            subject,
            html_content,
            smtp_config=smtp_config,
            organization_id=organization_id,
            failure_notice=failure_notice,
        )
        return job_id is not None

    @staticmethod
    async def send_email_with_attachment_async(
        to_email: str,
        subject: str,
        html_content: str,
        attachment_bytes: bytes,
        attachment_filename: str,
        smtp_config: dict | None = None,
        organization_id: UUID | None = None,
    ) -> bool:
        """Queue an email with attachment for durable delivery.

        Same contract as ``send_email_async``: queued in production, real
        send in TESTING.
        """
        mark_external_effect('email:queued-with-attachment')
        if settings.TESTING:
            result = await run_sync_in_thread(
                lambda: EmailService._send_email_with_attachment(  # noqa: SLF001
                    to_email,
                    subject,
                    html_content,
                    attachment_bytes,
                    attachment_filename,
                    smtp_config,
                )
            )
            return result.ok
        from app.services.email_jobs import enqueue_email_job

        job_id = await enqueue_email_job(
            to_email,
            subject,
            html_content,
            smtp_config=smtp_config,
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_filename,
            organization_id=organization_id,
        )
        return job_id is not None


email_service = EmailService()
