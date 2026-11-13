"""Deprecated event aliases with removal expiry.

**The register stands empty today.** Every qualifier it once named — nine
vertical aliases parked in the core ``SystemEvent`` enum, then the two
neutral-vocabulary spellings ``item.consumed``/``item.discarded`` — left
without a window. The last two were on the wire in the one sense that
matters for a deprecation window: administrators could subscribe to them,
and the names sat in ``webhook_endpoints.event_types`` rows. No database
outside disposable dev/demo data, which resets with its stack, held such
rows, so the aliases left without a window and without a migration rather
than carry a deadline for nobody.

The machinery below is not dead weight. An event deprecated once outside
subscribers can depend on it gets a real, dated window: register it
here, ``warn_if_deprecated`` logs once per process when it is emitted,
and the expiry test fails the build once ``removal_release`` ships.

Every entry carries a ``removal_release``: a unit test compares it against
the backend version in ``pyproject.toml`` and fails once the release is
reached, forcing either removal or an explicit expiry bump.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)

#: The release a fresh entry may name as its removal deadline: two minor
#: releases after the current one, the window CONTRACTS_STABILITY.md §2
#: promises a stable surface. An entry carries its own date; nothing here
#: moves when one lands.
REMOVAL_RELEASE = '0.14.0'


@dataclass(frozen=True)
class EventDeprecation:
    event: str
    replacement: str
    reason: str
    removal_release: str = REMOVAL_RELEASE


DEPRECATED_EVENTS: dict[str, EventDeprecation] = {}

_warned_once: set[str] = set()


def get_deprecation(event_name: str) -> EventDeprecation | None:
    return DEPRECATED_EVENTS.get(event_name)


def warn_if_deprecated(event_name: str) -> None:
    """Log a one-per-process warning when a deprecated event is emitted."""
    deprecation = DEPRECATED_EVENTS.get(event_name)
    if deprecation is None or event_name in _warned_once:
        return
    _warned_once.add(event_name)
    logger.warning(
        '[EventBus] deprecated event %r emitted — use %s instead (%s); '
        'alias removed in release %s',
        deprecation.event,
        deprecation.replacement,
        deprecation.reason,
        deprecation.removal_release,
    )
