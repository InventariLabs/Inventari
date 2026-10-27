"""Lot-trace sources — how a module names the movements it writes.

A recall asks one step back and one step forward: who supplied the batch,
and who it went to (EU 178/2002 Art. 18). Core holds the ledger, and the
ledger knows every movement of a batch, its date and quantity — but the
movement only says *what kind* of thing it came from (``reference_type``)
and which one (``reference_id``). The supplier on a receipt, the customer on
a delivery and the number printed on either live in the module that wrote
the movement, which Core must never import.

So a module registers a source here for each ``reference_type`` it writes,
and the trace asks it to describe the references it found. A source that
turns what it consumes into new batches — a production run — says so with
``transforms``, and the trace follows it to the batch it made.

Graceful degradation: a reference nobody describes still appears, with its
kind, date and quantity and no partner — the movement happened whether or
not the module that wrote it is installed today.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import LotTraceReferenceDTO


class LotTraceSource(ABC):
    """Describes the references of one ``reference_type`` for a lot's trace."""

    #: The ``StockMove.reference_type`` this source answers for.
    reference_type: str
    #: True when a reference of this type consumes batches and produces
    #: others under the same reference: the trace then follows each batch
    #: that came in under it to its own trace.
    transforms: bool = False

    @abstractmethod
    async def describe_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_ids: Sequence[UUID],
    ) -> dict[UUID, LotTraceReferenceDTO]:
        """What each of *reference_ids* is, within *organization_id*.

        A reference the source cannot find (another organization's, deleted)
        is left out of the answer rather than raising.
        """


_sources: dict[str, LotTraceSource] = {}


def register_lot_trace_source(source: LotTraceSource) -> None:
    """Register *source* for its ``reference_type`` (called by the owning module).

    Keyed by the type, so registering again — a module imported twice —
    replaces rather than duplicates.
    """
    _sources[source.reference_type] = source


def get_lot_trace_source(reference_type: str | None) -> LotTraceSource | None:
    """The source registered for *reference_type*, if any."""
    if reference_type is None:
        return None
    return _sources.get(reference_type)
