"""Domain events published by the purchase_orders module.

Canonical home — and now the only home — of the ``purchase_order.*`` and
``receipt.*`` events. The matching ``SystemEvent`` members were aliases
parked in the core table and were removed before this repository went
public; the strings did not change, because this enum carries the same
ones. Cross-module subscribers use the plain string values (event names are
contracts; importing another module's code is not allowed).
"""

from enum import StrEnum


class PurchaseOrderEvent(StrEnum):
    CONFIRMED = 'purchase_order.confirmed'
    COMPLETED = 'purchase_order.completed'
    CANCELLED = 'purchase_order.cancelled'
    RECEIPT_CREATED_FROM_PO = 'receipt.created_from_po'
