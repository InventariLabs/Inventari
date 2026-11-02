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

from .models import Document


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
    doc: Document, profile: Any, *, status: str | None = None
) -> bool:
    """Whether the profile asks for an approval of this document.

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
        value = document_value(doc)
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
    doc: Document, profile: Any, *, status: str | None = None
) -> SignOff:
    """The profile's half of the approval rule, about one document.

    ``unspecified`` is the profile's silence, which the approvals module reads
    as "the workflow alone decides". Only a document being confirmed or
    executed is weighed at all: a draft needs nothing yet.
    """
    weighed_status = doc.status if status is None else status
    if is_approval_required(doc, profile, status=weighed_status):
        return 'required'
    if weighed_status not in {'CONFIRMED', 'PENDING_APPROVAL'}:
        return 'not_required'
    if profile_names_what_needs_approval(profile):
        return 'not_required'
    return 'unspecified'
