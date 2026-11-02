"""The over-receipt rule, in one place.

A ramp receives what physically arrived, and the paperwork is sometimes
wrong: twelve on the pallet, ten on the order. The rule that decides when
that may be written was copied per door and each copy refused everything
past the expected figure — while a correction of the same line accepted
any amount an hour later.

It lives here once: a surplus is allowed within the organization's
over-receipt tolerance for anyone who may receive, and past that tolerance
it needs the ``warehouse:receive_over_tolerance`` permission. Every door
that raises a received quantity — the scan, the short receive, document
completion, the order guard and a positive correction — asks this same
question.

The permission is not a blank cheque. Past an optional hard ceiling the
organization sets, nobody may receive at all; and the doors where a person
states the number — the receive screen and the receiving session — ask the
holder to confirm a surplus past the tolerance before it is written, naming
the surplus and the line it lands on (``OverReceiptRefusedError`` carries
the question, the door asks it).

Quantities travel in the unit the caller works in; a caller that weighs
against an order line converts its own side to the stock unit first, the
way ``_po_receipt_guard`` already does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message, stated_quantity

from ._order_side import order_side_async

#: The organization setting this module reads. Stored under
#: ``module:warehouse`` through the module settings schema.
TOLERANCE_SETTING_KEY = 'over_receipt_tolerance_percent'

#: The setting past which nobody may receive, permission or not, in percent
#: over the same basis the tolerance is measured against. 0 means no ceiling.
CEILING_SETTING_KEY = 'over_receipt_ceiling_percent'

#: The reason code every surplus line carries. A short line names why with a
#: code; a surplus line does the same, and the screens render the code's own
#: label in the reader's language — a sentence stored beside it would reach
#: every reader in English.
SURPLUS_CODE = 'SURPLUS'


async def over_receipt_tolerance_percent_async(
    db: AsyncSession, org_id: UUID
) -> Decimal:
    """The organization's over-receipt tolerance in percent, 0 by default.

    A stored value that is not a number, or is negative, reads as no
    tolerance — the safe side of the setting.
    """
    raw = await core_api.settings.get_async(
        db, org_id, 'warehouse', TOLERANCE_SETTING_KEY, default=0
    )
    try:
        percent = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')
    return percent if percent > 0 else Decimal('0')


class OverReceiptRefusedError(ValueError):
    """A surplus past the tolerance, refused for want of the permission.

    The message is the refusal a reader without the permission gets.
    *question* is what a holder of the permission is asked instead, at a
    door where the person stating the number can answer: it names the
    surplus and the line it lands on, in the reader's language.
    """

    def __init__(self, message: str, *, question: str) -> None:
        super().__init__(message)
        self.question = question


class SurplusNeedsConfirmationError(AppException):
    """409 — a holder of the permission is asked before the surplus is written.

    The screen sends the same call again with the confirmation once the
    reader answers; the refusal rolled back everything the call had begun.
    """

    def __init__(self, question: str) -> None:
        super().__init__(
            status_code=409, code='SURPLUS_NEEDS_CONFIRMATION', message=question
        )


@contextmanager
def asking_the_holder(may_exceed: bool) -> Iterator[None]:
    """Turn a surplus refusal into a question for a holder of the permission.

    A door where the person stating the number can answer passes
    ``may_exceed and confirm_surplus`` down, so an unconfirmed holder meets
    the same refusal as anyone else; here it becomes the question. Anyone
    without the permission keeps the refusal.
    """
    try:
        yield
    except OverReceiptRefusedError as exc:
        if may_exceed:
            raise SurplusNeedsConfirmationError(exc.question) from exc
        raise


def surplus_question(
    *,
    product: str | None,
    quantity: Decimal,
    basis: Decimal,
    order_label: tuple[str, int] | None = None,
) -> str:
    """The question a holder is asked: the surplus, and the line it lands on.

    An order line is named by its order's number and its line number, the
    way the order's own screen lists it (*order_label*).
    """
    lang = get_current_lang()
    figures = {
        'product': product or '',
        'quantity': stated_quantity(quantity, lang),
        'surplus': stated_quantity(quantity - basis, lang),
        'basis': stated_quantity(basis, lang),
    }
    if order_label is None:
        return get_error_message('over_receipt_confirm_surplus', lang, **figures)
    order_number, line_number = order_label
    return get_error_message(
        'over_receipt_confirm_order_surplus',
        lang,
        order=order_number,
        line=line_number,
        **figures,
    )


async def _order_label_async(
    db: AsyncSession, org_id: UUID, order_line_id: UUID | None
) -> tuple[str, int] | None:
    """How the order names the line, when the order is there to be asked."""
    if order_line_id is None:
        return None
    orders = await order_side_async(db, org_id)
    if orders is None:
        return None
    return (await orders.get_line_labels_async(db, org_id, [order_line_id])).get(
        order_line_id
    )


async def assert_under_ceiling_async(
    db: AsyncSession, org_id: UUID, *, quantity: Decimal, basis: Decimal
) -> None:
    """Refuse *quantity* past the organization's hard ceiling, for anyone."""
    raw = await core_api.settings.get_async(
        db, org_id, 'warehouse', CEILING_SETTING_KEY, default=0
    )
    try:
        ceiling = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return
    if ceiling <= 0 or quantity <= over_receipt_ceiling(basis, ceiling):
        return
    lang = get_current_lang()
    raise ServiceRejectionError(
        'over_receipt_past_ceiling',
        quantity=stated_quantity(quantity, lang),
        basis=stated_quantity(basis, lang),
        ceiling=ceiling,
    )


def over_receipt_ceiling(basis: Decimal, tolerance_percent: Decimal) -> Decimal:
    """The most may be recorded without the permission: *basis* plus its percent."""
    return basis * (Decimal('1') + tolerance_percent / Decimal('100'))


async def order_surplus_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    quantity: Decimal,
    remaining: Decimal,
    may_exceed: bool,
    product: str | None,
    order_label: tuple[str, int] | None,
) -> tuple[str, str] | None:
    """The refusal and the holder's question for a surplus on an order line.

    *quantity* is past *remaining*, what is left on the order line. ``None``
    when the surplus may stand — the caller holds the permission, or it is
    within the organization's tolerance; past the hard ceiling it is refused
    for anyone, with no question to ask. Otherwise the refusal a reader
    without the permission gets, and the question a holder is asked instead.
    """
    await assert_under_ceiling_async(db, org_id, quantity=quantity, basis=remaining)
    if may_exceed:
        return None
    tolerance = await over_receipt_tolerance_percent_async(db, org_id)
    if quantity <= over_receipt_ceiling(remaining, tolerance):
        return None
    refusal = get_error_message(
        'document_exceeds_order_line',
        get_current_lang(),
        quantity=quantity,
        remaining=remaining,
        tolerance=tolerance,
    )
    question = surplus_question(
        product=product, quantity=quantity, basis=remaining, order_label=order_label
    )
    return refusal, question


async def assert_over_receipt_allowed_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    quantity: Decimal,
    basis: Decimal,
    may_exceed: bool,
    product: str | None = None,
    order_line_id: UUID | None = None,
) -> None:
    """Refuse *quantity* past *basis* when the caller may not exceed tolerance.

    *quantity* is what the line would stand at after this action, and
    *basis* is what the rule measures it against — the line's expected
    quantity, or what is left on the order line when the document line
    names one (*order_line_id*). The permission lifts the tolerance up to
    the organization's hard ceiling, if one is set. *product* and the
    order line name what a holder is asked about.
    """
    if quantity <= basis:
        return
    await assert_under_ceiling_async(db, org_id, quantity=quantity, basis=basis)
    if may_exceed:
        return
    tolerance = await over_receipt_tolerance_percent_async(db, org_id)
    if quantity <= over_receipt_ceiling(basis, tolerance):
        return
    raise OverReceiptRefusedError(
        get_error_message(
            'over_receipt_needs_permission',
            get_current_lang(),
            quantity=quantity,
            tolerance=tolerance,
        ),
        question=surplus_question(
            product=product,
            quantity=quantity,
            basis=basis,
            order_label=await _order_label_async(db, org_id, order_line_id),
        ),
    )
