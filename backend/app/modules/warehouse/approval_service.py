"""The document profile's own approval rule — the *what* of WHEN approval is needed.

This answers what the *profile* asks for: a listed type, or a value over the
threshold. The *who* belongs to the workflow, and the approvals module's
document gate holds the one rule confirmation and completion both ask: a
workflow on its own demands approval only while the profile names nothing —
configuring who approves is itself the statement that documents are approved
before they move — while a configured threshold or type list is the filter
that workflow then carries out. It reads this half through
``warehouse_api.document_sign_off_async``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import quantise
from app.core.public_api import core_api

from . import document_types as dt
from .models import Document, DocumentLine


class ApprovalError(ValueError):
    """Raised for approval workflow violations."""


def document_value(doc: Document) -> Decimal | None:
    """What the document is worth, or ``None`` when nobody has said.

    ``None`` used to be flattened to zero here, which put the one document
    whose worth nobody wrote down under every threshold there is. Zero and
    unknown are different answers — the cost layers keep them apart for the
    same reason — and the threshold is entitled to know which it has.
    """
    return doc.total_net


async def _line_template_id_async(
    db: AsyncSession, doc: Document, line: DocumentLine
) -> UUID | None:
    """The product whose cost layers the line would draw, the executor's way."""
    if line.product_template_id is not None or line.item_id is None:
        return line.product_template_id
    item = await core_api.items.get_async(db, doc.organization_id, line.item_id)
    return item.template_id if item is not None else None


async def weighed_value_async(db: AsyncSession, doc: Document) -> Decimal | None:
    """What the threshold weighs: the stated value, or what a write-off will cost.

    A write-off asks for no price, and is worth what the cost layers it draws
    were worth, which is only written when it is posted. Until then it had no
    value, and no value is over every limit: two rolls of tape worth 25 under
    a threshold of 500 raised an approval request. The goods already carry a
    cost, so the threshold reads the layers' rate, the same indicative figure
    a forecast does. A line nothing can value still leaves the whole document
    unknown, which keeps the rule ``document_value`` states.
    """
    value = document_value(doc)
    if value is not None or not dt.is_scrap(doc.type):
        return value
    templates = [await _line_template_id_async(db, doc, line) for line in doc.lines]
    known = [template_id for template_id in templates if template_id is not None]
    rates = await core_api.valuation.get_rates_batch_async(
        db, doc.organization_id, known
    )
    total = Decimal('0')
    for line, template_id in zip(doc.lines, templates, strict=True):
        rate = rates.get(template_id) if template_id is not None else None
        if rate is None:
            return None
        try:
            quantity = await core_api.uoms.to_stock_uom_async(
                db,
                doc.organization_id,
                template_id,
                line.expected_quantity,
                line.uom_id,
            )
        except ValueError:
            return None
        total += quantity * rate
    return quantise(total)


def required_types(profile: Any) -> list[str]:
    """The profile's "always require approval for" list, however it is stored.

    A JSON list in the column, but a comma-joined string was written by an
    older form and may still be sitting in a row — one reading of the field,
    so the rule and the "does the profile say anything" question cannot
    drift apart.
    """
    types = profile.approval_required_for_types or []
    if isinstance(types, str):
        return [name for name in types.split(',') if name]
    return list(types)


def profile_names_what_needs_approval(profile: Any) -> bool:
    """Whether the profile itself names what needs signing off.

    A threshold — zero counts, it is still a limit — or a non-empty type
    list is the organization saying *what* is controlled. Both empty is
    silence, and silence is what ``_approval_gate`` reads as "the workflow
    alone decides", the organization saying "everything" by naming who
    approves.
    """
    return profile.approval_threshold is not None or bool(required_types(profile))


def is_approval_required(
    doc: Document,
    profile: Any,
    *,
    value: Decimal | None,
    status: str | None = None,
) -> bool:
    """Whether the profile asks for an approval of this document.

    ``value`` is what the threshold weighs (``weighed_value_async``).
    ``status`` weighs the document at a status other than the one it holds
    now. Its only caller, ``document_sign_off``, is asked about both halves of
    the rule at the same status, so the profile half has to be askable about
    the document a step ahead of the state it is in.
    """
    weighed_status = doc.status if status is None else status
    if weighed_status not in {'CONFIRMED', 'PENDING_APPROVAL'}:
        return False

    if doc.type in required_types(profile):
        return True

    threshold = profile.approval_threshold
    if threshold is not None:
        # An unpriced document cannot be shown to be under the limit, and a
        # limit that lets through whatever it cannot measure is not a limit.
        # The way out is either way round: price the document, or have it
        # approved.
        if value is None or value > threshold:
            return True

    return False


#: What the profile says about signing a document off: it asks for it, it
#: names what needs it and this is not that, or it names nothing at all.
SignOff = Literal['required', 'not_required', 'unspecified']


def document_sign_off(
    doc: Document,
    profile: Any,
    *,
    value: Decimal | None,
    status: str | None = None,
) -> SignOff:
    """The profile's half of the approval rule, about one document.

    ``unspecified`` is the profile's silence, which the approvals module reads
    as "the workflow alone decides". Only a document being confirmed or
    executed is weighed at all: a draft needs nothing yet.
    """
    weighed_status = doc.status if status is None else status
    if is_approval_required(doc, profile, value=value, status=weighed_status):
        return 'required'
    if weighed_status not in {'CONFIRMED', 'PENDING_APPROVAL'}:
        return 'not_required'
    if profile_names_what_needs_approval(profile):
        return 'not_required'
    return 'unspecified'
