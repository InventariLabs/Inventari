"""Who wants to hear that a request about their target was settled.

The engine decides; the module that owns the target has to act on the
decision. Approving a request used to end at ``request.status = 'APPROVED'``
and nothing else -- the document it was about stayed in PENDING_APPROVAL, so
a document that was approved and ready to post looked, on the list and in
the "Pending Approval" filter, exactly like one still waiting for somebody.

Reading the other module's tables from here is not an option (the engine
never does), and the consuming module cannot poll. So the direction is the
same one ``target_summaries`` already takes: a module that requests approval
registers a listener for its own target type at import time, and the engine
tells whoever is registered. A target type with no listener behaves exactly
as before.

The listener runs inside the deciding transaction, so what it writes commits
with the decision or rolls back with it. It must not commit.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TargetDecision:
    """How one request about one target ended."""

    organization_id: UUID
    target_type: str
    target_id: UUID
    request_id: UUID
    # The request's new status: APPROVED, REJECTED or CANCELLED.
    outcome: str
    requester_id: UUID
    # Who made the decision, when the door that published it knows; the
    # target's own journal reads it to name the actor of the act the
    # decision caused.
    decided_by: UUID | None = None
    # What the decider wrote, when they wrote anything.
    notes: str | None = None
    # A CANCELLED request closed because its workflow was switched off, not
    # withdrawn by anyone: the target goes on as if no approval had been
    # asked. A withdrawal never means that -- an order whose requester pulled
    # the request back is not approved by it.
    released: bool = False


class TargetDecisionRefusedError(Exception):
    """Raised by a listener whose follow-up is what the decision promised.

    Most follow-ups trail the decision: the record of what a person did stands
    even when the consuming module fails to keep up. Some are the decision --
    an approval that was granted to post a document means nothing if the
    posting cannot happen. A listener wraps that failure in this exception and
    the decision is refused with it: the original error reaches the person
    deciding, and the deciding transaction rolls back whole.
    """

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


TargetDecisionListener = Callable[[AsyncSession, TargetDecision], Awaitable[None]]

_LISTENERS: dict[str, TargetDecisionListener] = {}


def register_target_decision_listener(
    target_type: str, listener: TargetDecisionListener
) -> None:
    """Claim the decisions on one target type.

    Registering twice for the same type replaces the earlier listener, which
    keeps module reloads (and tests) from accumulating stale entries.
    """
    _LISTENERS[target_type] = listener


async def notify_target_decided(db: AsyncSession, decision: TargetDecision) -> None:
    """Tell the owner of the target how the request about it ended.

    A listener that raises must not take the decision down with it: the
    decision is the record of what a person did, and it stands whether or
    not the consuming module managed to follow it -- unless the listener
    raises ``TargetDecisionRefusedError``, which takes the decision down too.
    """
    listener = _LISTENERS.get(decision.target_type)
    if listener is None:
        return
    try:
        await listener(db, decision)
    except TargetDecisionRefusedError as refusal:
        # Not ``from refusal``: a listener raises the refusal ``from`` the
        # cause, so chaining back would make the two each other's cause, and
        # a walk down ``__cause__`` (the retry middleware's SQLSTATE lookup)
        # would never end — the request hung instead of answering.
        raise refusal.cause from None
    except Exception as exc:  # noqa: BLE001 — a decision is never lost over a follow-up
        logger.warning(
            '[Approvals] %s listener failed for %s (%s): %s',
            decision.target_type,
            decision.target_id,
            decision.outcome,
            exc,
        )
