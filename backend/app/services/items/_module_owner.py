"""Which vertical module a record *wrote*, resolved once on write.

The two SQL predicates that read the answer back — what a module counts as
its own, and what a general list may show — live in
``app.core.module_ownership``: vertical modules ask the same question and
cannot import from ``app.services``.

A module writes its data under a ``meta_data`` namespace named after itself
(AGENTS.md, "meta_data namespace convention"), so the namespace is the
answer — resolved once on write and stored on ``Item.module_name`` rather
than asked of a JSONB column on every list query.

Derived, never taken from the request body: a client that could name its own
owner could hide any record it liked from the lists that use this.
"""

from typing import Any

from app.core.module_scope import get_claimed_modules


def resolve_module_owner(meta_data: dict[str, Any] | None) -> str | None:
    """The vertical module whose namespace this record carries, if any.

    Sorted rather than first-written: a record carrying two claimed
    namespaces has to resolve the same way every time it is saved.
    """
    if not meta_data:
        return None

    claimed = get_claimed_modules()
    for namespace in sorted(meta_data):
        if namespace in claimed:
            return namespace
    return None
