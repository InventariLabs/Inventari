"""The set of statuses a document can be cancelled in has two readers.

One is ``cancel_document`` in ``_document_workflow_transitions.py``. The other
is the screen — ``frontend/src/modules/warehouse/components/
DocumentActionButtons.tsx`` — which has to offer the action wherever the API
would perform it. It did not: cancelling was on a draft only, so a document
that stuck at execution went on holding its reservation over a whole shelf and
no role had a button to release it. The API answered 200 to the same request
all along.

This test pins the set so that widening or narrowing it fails here first, with
the file to change named in as many words.
"""

from __future__ import annotations

import pytest

from app.modules.warehouse._document_workflow_transitions import (
    CANCELLABLE_STATUSES,
    RESERVING_STATUSES,
)

# Mirrored by ``CANCELLABLE`` in DocumentActionButtons.test.tsx.
CANCELLABLE = {'DRAFT', 'CONFIRMED', 'PENDING_APPROVAL'}


@pytest.mark.unit
def test_cancel_accepts_exactly_the_statuses_the_screen_offers() -> None:
    assert set(CANCELLABLE_STATUSES) == CANCELLABLE, (
        'cancel_document changed which statuses it accepts. The screen offers '
        'the action from its own list — update CANCELLABLE in '
        'frontend/src/modules/warehouse/components/DocumentActionButtons.tsx '
        'and its test, or a role able to cancel through the API will have no '
        'button for it.'
    )


@pytest.mark.unit
def test_the_reserving_statuses_are_the_ones_worth_a_word_in_the_dialog() -> None:
    """Cancelling these gives stock back, and the dialog says so.

    ``confirmDialog.cancelReservedMessage`` is shown for exactly this set;
    a draft holds nothing, so it keeps the plain sentence.
    """
    assert set(RESERVING_STATUSES) == {'CONFIRMED', 'PENDING_APPROVAL'}
    assert RESERVING_STATUSES < CANCELLABLE_STATUSES
