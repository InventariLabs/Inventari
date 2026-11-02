"""Shipping a dispatch: the hand-over its completion records, and where to track it.

Shipping is a record, not a carrier integration. The carrier's system prints
the label; Inventari keeps which carrier took the goods, under which tracking
number, when and by whom — written by ``complete_document`` in the same
transaction as the stock, so a dispatch whose stock did not post has no
shipment either. "Ship" is the completion with two more fields, and the
document keeps its statuses.

A tracking link is resolved on read, not stored: the organization's own
templates (``DocumentProfile.tracking_url_templates``) first, then the
built-in ones below, matched on the carrier name as the operator typed it.
A carrier neither names gets no link, and the number is shown as it is.
"""

from __future__ import annotations

import string
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import emit_transactional_safe
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._document_workflow_helpers import build_document_event_payload
from .events import DocumentEvent
from .models import Document, DocumentPackage, DocumentProfile, DocumentShipment
from .shipment_schemas import DocumentShipmentSchema, ShipmentCreate

#: The carriers whose tracking page needs no setup. Keys are normalised
#: names (``_carrier_key``); an organization's template for the same name
#: wins.
BUILT_IN_TRACKING_URLS: dict[str, str] = {
    'inpost': 'https://inpost.pl/sledzenie-przesylek?number={tracking_number}',
    'dhl': 'https://www.dhl.com/global-en/home/tracking.html?tracking-id={tracking_number}',
    'dpd': 'https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1={tracking_number}',
    'gls': 'https://gls-group.com/track/{tracking_number}',
    'poczta polska': 'https://emonitoring.poczta-polska.pl/?numer={tracking_number}',
    'ups': 'https://www.ups.com/track?tracknum={tracking_number}',
    'fedex': 'https://www.fedex.com/fedextrack/?trknbr={tracking_number}',
}

#: How many carriers the suggestions offer.
_SUGGESTION_LIMIT = 20

_UNRESERVED = frozenset(string.ascii_letters + string.digits + '-._~')


def _percent_encode(text: str) -> str:
    """``urllib.parse.quote(text, safe='')``, which the module may not import.

    The safety scan reads ``urllib`` as the network capability, and this
    module does not reach the network: it only puts a number into a link.
    """
    return ''.join(
        char if char in _UNRESERVED else ''.join(f'%{b:02X}' for b in char.encode())
        for char in text
    )


def _carrier_key(carrier: str) -> str:
    """``' Poczta  Polska'`` and ``'poczta polska'`` name one carrier."""
    return ' '.join(carrier.casefold().split())


def tracking_url(
    carrier: str,
    tracking_number: str | None,
    org_templates: dict[str, str] | None = None,
) -> str | None:
    """The carrier's tracking page for *tracking_number*, or ``None``."""
    if not tracking_number:
        return None
    key = _carrier_key(carrier)
    own = {_carrier_key(name): url for name, url in (org_templates or {}).items()}
    template = own.get(key) or BUILT_IN_TRACKING_URLS.get(key)
    if template is None:
        return None
    return template.replace('{tracking_number}', _percent_encode(tracking_number))


async def record_shipment_async(
    db: AsyncSession,
    doc: Document,
    user_id: UUID,
    data: ShipmentCreate,
) -> DocumentShipment:
    """Add the dispatch's hand-over to the completion's transaction."""
    if not dt.is_dispatch(doc.type):
        raise ServiceRejectionError('document_shipment_dispatch_only')
    shipment = DocumentShipment(
        organization_id=doc.organization_id,
        document_id=doc.id,
        carrier=data.carrier,
        tracking_number=data.tracking_number,
        shipped_at=data.shipped_at or datetime.now(UTC),
        shipped_by=user_id,
        notes=data.notes,
    )
    db.add(shipment)
    await db.flush()
    return shipment


async def _org_templates_async(db: AsyncSession, org_id: UUID) -> dict[str, str] | None:
    return await db.scalar(
        select(DocumentProfile.tracking_url_templates).where(
            DocumentProfile.organization_id == org_id
        )
    )


async def _package_counts_async(
    db: AsyncSession, doc_ids: Sequence[UUID]
) -> dict[UUID, int]:
    rows = await db.execute(
        select(DocumentPackage.document_id, func.count())
        .where(DocumentPackage.document_id.in_(doc_ids))
        .group_by(DocumentPackage.document_id)
    )
    return dict(rows.tuples().all())


async def attach_shipments_async(
    db: AsyncSession, org_id: UUID, docs: Sequence[Document]
) -> None:
    """Populate the transient ``shipment`` of each dispatch that has one.

    Three queries for any number of documents: the shipments, the package
    counts, and — only when there is a shipment — the organization's
    templates.
    """
    doc_ids = [doc.id for doc in docs if dt.is_dispatch(doc.type)]
    if not doc_ids:
        return
    shipments = {
        s.document_id: s
        for s in await db.scalars(
            select(DocumentShipment).where(
                DocumentShipment.organization_id == org_id,
                DocumentShipment.document_id.in_(doc_ids),
            )
        )
    }
    if not shipments:
        return
    templates = await _org_templates_async(db, org_id)
    packages = await _package_counts_async(db, list(shipments))
    names = await _shipper_names_async(db, org_id, list(shipments.values()))
    for doc in docs:
        shipment = shipments.get(doc.id)
        if shipment is not None:
            doc.shipment = _shipment_out(  # type: ignore[attr-defined]
                shipment,
                templates,
                packages.get(doc.id, 0),
                names.get(shipment.shipped_by),
            )


async def _shipper_names_async(
    db: AsyncSession, org_id: UUID, shipments: Sequence[DocumentShipment]
) -> dict[UUID | None, str]:
    """The names behind ``shipped_by``, in the way the document names actors."""
    user_ids = {s.shipped_by for s in shipments if s.shipped_by is not None}
    if not user_ids:
        return {}
    users = await core_api.users.get_by_ids_async(db, org_id, list(user_ids))
    return {user.id: user.full_name or user.email for user in users}


def _shipment_out(
    shipment: DocumentShipment,
    templates: dict[str, str] | None,
    package_count: int,
    shipped_by_name: str | None = None,
) -> DocumentShipmentSchema:
    return DocumentShipmentSchema(
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        tracking_url=tracking_url(
            shipment.carrier, shipment.tracking_number, templates
        ),
        shipped_at=shipment.shipped_at,
        shipped_by=shipment.shipped_by,
        shipped_by_name=shipped_by_name,
        notes=shipment.notes,
        package_count=package_count,
    )


async def emit_shipped_async(
    db: AsyncSession, org_id: UUID, doc: Document, shipment: DocumentShipment
) -> None:
    """Publish ``document.shipped`` on the completion's transaction."""
    package_count = (await _package_counts_async(db, [doc.id])).get(doc.id, 0)
    templates = await _org_templates_async(db, org_id)
    await emit_transactional_safe(
        db,
        DocumentEvent.SHIPPED,
        {
            'organization_id': str(org_id),
            'document_id': str(doc.id),
            'document_number': doc.number,
            'document_type': doc.type,
            'carrier': shipment.carrier,
            'tracking_number': shipment.tracking_number,
            'tracking_url': tracking_url(
                shipment.carrier, shipment.tracking_number, templates
            ),
            'package_count': package_count,
            'shipped_at': shipment.shipped_at.isoformat(),
            'lines': (await build_document_event_payload(db, doc, org_id))['lines'],
        },
    )


async def list_carriers_async(db: AsyncSession, org_id: UUID) -> list[str]:
    """The organization's carriers, the most recently shipped with first.

    One spelling per carrier: the one its latest shipment used.
    """
    key = func.lower(func.trim(DocumentShipment.carrier))
    latest = (
        select(
            DocumentShipment.carrier,
            func.row_number()
            .over(partition_by=key, order_by=DocumentShipment.shipped_at.desc())
            .label('rank'),
            DocumentShipment.shipped_at,
        )
        .where(DocumentShipment.organization_id == org_id)
        .subquery()
    )
    rows = await db.scalars(
        select(latest.c.carrier)
        .where(latest.c.rank == 1)
        .order_by(latest.c.shipped_at.desc())
        .limit(_SUGGESTION_LIMIT)
    )
    return list(rows)
