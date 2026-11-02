"""Scan provider resolving document numbers printed on warehouse documents.

the PDF printout carries ``document.number`` in Code128 and QR
(``document_pdf_service``), but no provider in the scan registry understood
document numbers — a scanned printout fell through every provider and the
API answered 404 with a *label* message. This provider closes the loop.

``can_handle`` is deliberately broad (always True, like the storage-context
provider): ``DocumentProfile.numbering_format`` is configurable per
organization and may produce codes indistinguishable from product barcodes
(pure digits), so a format-based claim would guess where the lookup can
decide. The ``(organization_id, number)`` lookup — over the unique index —
is the only arbiter: a miss returns None and the code keeps flowing to the
next provider (product barcodes, OFF, …).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LabelScanDTO, UserContextDTO
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.scan_registry import ScanProvider

from .models import Document, DocumentStatus

logger = get_logger(__name__)

# Document types whose CONFIRMED state means floor work: a receipt or
# issue in progress is worked with a printout in hand at the shelf, so its
# scan opens the receiving/picking session instead of a passive preview.
_EXECUTABLE_TYPES = frozenset({'IN', 'INTERNAL_IN', 'OUT', 'INT', 'INTERNAL_OUT'})


class DocumentScanProvider(ScanProvider):
    """Resolves document numbers (printed on the PDF) to their documents."""

    async def can_handle(self, code: str) -> bool:
        return True

    async def handle(
        self, code: str, user: UserContextDTO, db: AsyncSession
    ) -> LabelScanDTO | None:
        if not user.organization_id:
            return None

        # Registered at startup regardless of which modules an organization
        # enabled — with the module off the code must fall through (None),
        # never break the chain for a feature the org does not use.
        module_enabled = await core_api.organizations.is_module_enabled_async(
            db, user.organization_id, 'warehouse'
        )
        if not module_enabled:
            return None

        document = (
            await db.scalars(
                select(Document).where(
                    Document.organization_id == user.organization_id,
                    Document.number == code,
                )
            )
        ).first()
        if not document:
            return None

        # A scan opens the document; an in-progress document goes straight
        # into continuation. DRAFT continues into the edit form. A CONFIRMED
        # document is real work on the floor — the printout in hand is a
        # receiving or picking list — so it opens into the execution flow;
        # anything finished opens as a preview.
        if document.status == DocumentStatus.DRAFT.value:
            mode = 'continue'
        elif (
            document.status == DocumentStatus.CONFIRMED.value
            and document.type in _EXECUTABLE_TYPES
        ):
            mode = 'execute'
        else:
            mode = 'preview'
        return LabelScanDTO(
            status='document',
            label_code=document.number,
            message_key='scan:result.document',
            message_params={'number': document.number},
            action='open_document',
            document={
                'id': str(document.id),
                'number': document.number,
                'status': document.status,
                'type': document.type,
            },
            document_mode=mode,
        )
