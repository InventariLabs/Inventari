"""The words that differ between the two WMS directions, in one place.

Picking and receiving run on the same tables, the same lifecycle and the
same wire shapes — a session, its lines, scan, skip, undo, complete, cancel.
What differs is vocabulary: the stored name of a short terminal status, the
field a counted quantity travels under. Those words were copied into every
twin function, and the copies drifted: the empty-session guard and the undo
filter each landed on one side only. They live here once so the machines in
``_wms_session_ops`` and ``_wms_scan_ops`` are written once.

A fully resolved line is stored as ``picked`` for both directions — it is
one column in one table — while the wire word differs; ``done_word`` carries
the wire word and the machine keeps the stored one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class WmsDirection:
    """One WMS session kind's vocabulary and the policies named after it."""

    #: 'picking' | 'receiving' — the session's direction.
    kind: str
    #: Stored terminal status of a session that holds a short line.
    short_status: Literal['short_pick', 'short_receive']
    #: Prefix of the advisory lock a session start takes on the document.
    lock_prefix: str
    #: Wire name of the counted quantity in a scan response.
    quantity_key: str
    #: Wire word for a fully resolved line; the stored word is 'picked'.
    done_word: str
    #: 'pick' | 'receive' — the verb scan messages use.
    verb: str
    #: Marker new sessions carry, when a direction needs one.
    session_meta: dict[str, Any] | None = None


PICKING = WmsDirection(
    kind='picking',
    short_status='short_pick',
    lock_prefix='pick_session',
    quantity_key='picked_quantity',
    done_word='picked',
    verb='pick',
)

RECEIVING = WmsDirection(
    kind='receiving',
    short_status='short_receive',
    lock_prefix='receive_session',
    quantity_key='received_quantity',
    done_word='received',
    verb='receive',
    session_meta={'direction': 'inbound'},
)
