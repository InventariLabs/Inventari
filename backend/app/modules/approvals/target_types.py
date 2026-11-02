from enum import StrEnum

# What can be held for approval, in two shapes — both integrated, and the
# difference is worth knowing before adding a third.
#
# A *gated* target is refused at the act itself: the module calls
# check_and_block before posting or issuing, and the caller gets a refusal
# naming the missing approval. A *requesting* target raises the request
# itself and sits in a pending state until the decision arrives, so there is
# nothing left for a gate to guard.
#
# Every one of them registers a summary provider, which is what lets the
# approvals queue describe the thing it is asking about.
#
# The explanation lives here rather than in a docstring on purpose: this
# enum is rendered into the OpenAPI schema, and a paragraph of ours ends up
# in the public contract every client generates from.


class TargetType(StrEnum):
    """A thing an approval workflow can be attached to."""

    # Gated: document_gate.py is a pre-post check this module registers with
    # the warehouse; it holds a document at confirmation and calls
    # check_and_block before posting.
    DOCUMENT = 'document'

    # Gated: equipment/_assignment_service.py calls check_and_block before an
    # asset is handed over; UI in _router_approvals.py.
    EQUIPMENT_CHECKOUT = 'equipment_checkout'

    # Requesting: confirming an order raises the request and leaves the order
    # PENDING_APPROVAL (_service_workflow.py), so it never reaches a state a
    # gate would have to guard; UI in _router_approval.py.
    PURCHASE_ORDER = 'purchase_order'


# The target types whose request *is* the whole control: releasing one leaves
# the target where the request was taking it (a released order is confirmed),
# and nothing of its own guards it afterwards. A gated target, by contrast,
# goes back under its own module's gate — the asking module's rule, which may
# still refuse it — so what still demands an approval of a released target is
# answered by that module, through the scope provider it registers, and not
# here. A target type missing from this set is treated as gated: the closure
# notice then only states what the module's scope says, rather than promising
# onward execution nobody has confirmed.
REQUESTING_TARGET_TYPES: frozenset[str] = frozenset({TargetType.PURCHASE_ORDER})
