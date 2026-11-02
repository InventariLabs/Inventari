"""Public Cross-Module API for the printing module.

Other modules (e.g. warehouse → "send this package's label to the printer")
queue labels through these methods without importing printing internals.
Labelling is always on (``ALWAYS_ON_MODULES``), so there is no disabled
state to degrade to: what can be missing is a printer, and that refusal is
the queue's own, in the reader's language.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .services import print_queue_service


class PrintingAPI:
    """Single public entry point for cross-module use of the print queue.

    Mirrors the ``approvals_api`` / ``maker_api`` pattern (AGENTS.md
    §Cross-Module API): one public API per module, no internal model or
    service imports allowed in consumers.
    """

    async def queue_label_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        user_id: UUID | None,
        *,
        short_code: str,
        caption: str | None,
        qr_url: str,
        read_permission: str,
        agent_id: UUID | None = None,
        width_mm: float = 50.0,
        height_mm: float = 24.0,
    ) -> UUID:
        """Queue one QR label for a printer and return the job's id.

        ``short_code`` prints under the QR, ``caption`` beside it, and the QR
        carries ``qr_url``. ``read_permission`` is the read the caller's
        record answers to: the queue lists and resends the job only to its
        holders. ``agent_id`` may be left out while the
        organization has one printer; without any, or with several and none
        named, the refusal is the queue's own, in the reader's language.
        """
        job = await print_queue_service.queue_drawn_label_async(
            db,
            organization_id,
            user_id,
            short_code=short_code,
            caption=caption,
            qr_url=qr_url,
            read_permission=read_permission,
            agent_id=agent_id,
            width_mm=width_mm,
            height_mm=height_mm,
        )
        return job.id


printing_api = PrintingAPI()
