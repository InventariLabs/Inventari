"""Marker for a public_api method that is correct without an organization.

The architecture lint (``_check_public_api_missing_org``) refuses a method
that is addressed by a row identifier yet takes no ``organization_id`` and
carries no ``UserContextDTO`` / ``OrganizationDTO``: isolation then rests on
the caller passing an id from its own organization. A few methods are right
that way — rows with no organization column at all, rows addressed through
the user whose organization is resolved inside the call, a deliberate
cross-organization repair. Those say so here, with the reason, where the
next reader of the method meets it.

The decorator does nothing at runtime; the lint reads the reason from the
source and ignores one that is not a literal, non-blank string.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar('F', bound=Callable[..., object])


def without_org_scope(reason: str) -> Callable[[F], F]:
    """Declare that the decorated method needs no organization, and why."""
    del reason  # read from the source by the lint, not at runtime

    def mark(func: F) -> F:
        return func

    return mark
