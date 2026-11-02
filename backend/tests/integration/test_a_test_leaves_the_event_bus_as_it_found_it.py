"""A test leaves the event bus with the subscriptions it found.

The bus is one object for a whole worker process, so a subscription a
fixture makes and never takes back is still there for every later test on
that worker. ``db_session`` starts the purchase-orders module for each
test, and starting it subscribes the order recalculation to the documents'
events; nothing took it back. By the 900th test on a worker, completing one
receipt recalculated its order 900 times, and the purchase-order tests,
which are collected last, took 10-15 s each instead of about one.

Alone, this test finds a clean bus whether the fixture tidies up or not.
It speaks when another test using ``db_session`` ran before it on the same
worker — which in the full suite is nearly always.
"""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy.orm import Session

from app.core.events import event_bus

pytestmark = pytest.mark.integration


def test_no_handler_is_subscribed_twice(db_session: Session) -> None:
    repeated = {
        f'{event} → {name}': count
        for event, entries in event_bus._listeners.items()
        for name, count in Counter(
            event_bus.name_of(callback) for callback, _, _ in entries
        ).items()
        if count > 1
    }

    assert repeated == {}
