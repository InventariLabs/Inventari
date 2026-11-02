"""Domain events published by the warehouse module.

Canonical home of the ``document.*`` event names. The matching ``SystemEvent``
members were aliases parked in the core table and were removed before this
repository went public; the strings did not change, because this enum carries
the same ones. The payload contracts still live in the core table until the
planned move, like the other module-owned contracts. Cross-module subscribers
use the plain string values (event names are contracts; importing another
module's code is not allowed).
"""

from enum import StrEnum


class DocumentEvent(StrEnum):
    CONFIRMED = 'document.confirmed'
    COMPLETED = 'document.completed'
    CANCELLED = 'document.cancelled'
    SHIPPED = 'document.shipped'
