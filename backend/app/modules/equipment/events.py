"""Domain events published by the equipment module.

Canonical home — and now the only home — of the ``equipment.*`` events.
The matching ``SystemEvent``
members were aliases parked in the core table and were removed before this
repository went public; the strings did not change, because this enum
carries the same ones. Cross-module subscribers use the plain string values
(event names are contracts; importing another module's code is not
allowed).
"""

from enum import StrEnum


class EquipmentEvent(StrEnum):
    CHECKOUT = 'equipment.checkout'
    CHECKIN = 'equipment.checkin'
