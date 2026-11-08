"""Module-safe transactional email API.

Modules must send email through this CoreAPI surface rather than importing
``email_service`` directly, so the architecture rule (no ``app.services``
imports in module code) holds. A mail queued for an organization leaves through
the server it named in Settings → Email, and through the installation's own
server when it named none. SMTP is best-effort: callers should treat the
boolean result as informational and never let an email failure block business
logic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.public_api._access import reads, writes
from app.services.email_service import (
    EmailService,
    email_button,
    email_fallback_link,
    email_shell,
)


class CoreEmailAPI:
    """Public Core API for sending transactional email from modules."""

    @staticmethod
    @reads
    def render_shell(heading: str, body_html: str, footer: str) -> str:
        """The card every transactional email arrives in.

        A module that builds its own would restyle one email out of four
        the next time the card changes — which is the state this replaced.
        *body_html* is inserted as it is, so anything a person typed has to
        be escaped before it gets here.
        """
        return email_shell(heading, body_html, footer)

    @staticmethod
    @reads
    def render_button(url: str, label: str) -> str:
        """The one centred call to action these emails carry."""
        return email_button(url, label)

    @staticmethod
    @reads
    def render_fallback_link(intro: str, url: str) -> str:
        """The address spelled out, for a client that shows no button."""
        return email_fallback_link(intro, url)

    @staticmethod
    @reads
    def is_configured() -> bool:
        """Whether a message sent through ``send_async`` could leave at all.

        The production path queues and answers ``True`` once the row is
        accepted, mail server or not, so its result cannot tell a module that
        nothing will ever arrive. Ask this first when the reader is owed that.
        """
        return EmailService.is_configured()

    @staticmethod
    @writes
    async def send_async(
        to_email: str,
        subject: str,
        html_content: str,
        smtp_config: dict[str, Any] | None = None,
        *,
        organization_id: UUID,
    ) -> bool:
        """Send an HTML email asynchronously (SMTP I/O offloaded to a thread).

        Returns ``True`` on success, ``False`` on SMTP failure.

        ``organization_id`` is the tenant the mail belongs to, and it is
        required for the same reason it is required on the attachment twin
        beside it: the durable queue retries for about seven minutes and
        then marks the row failed, and the only way a human ever meets that
        row is through the organization it names. A mail queued without one
        is visible to nobody and ends its life in the container log.

        This is a breaking change for a module outside this tree that calls
        the facade positionally — deliberately, because the alternative is a
        parameter that can be forgotten, and a forgotten tenant is the
        defect itself rather than a lesser form of it.
        """
        return await EmailService.send_email_async(
            to_email,
            subject,
            html_content,
            smtp_config,
            organization_id=organization_id,
        )

    @staticmethod
    @writes
    async def send_with_attachment_async(
        to_email: str,
        subject: str,
        html_content: str,
        attachment_bytes: bytes,
        attachment_filename: str,
        smtp_config: dict[str, Any] | None = None,
        *,
        organization_id: UUID,
    ) -> bool:
        """Send an HTML email with an attachment via the durable queue.

        ``organization_id`` is required tenant tagging for the durable
        email queue (filtering/audit). Returns ``True`` on success,
        ``False`` on failure — best-effort, never block business logic on it.
        """
        return await EmailService.send_email_with_attachment_async(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_filename,
            smtp_config=smtp_config,
            organization_id=organization_id,
        )
