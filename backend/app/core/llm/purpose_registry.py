"""Purpose registry — a flat module-level dict of named purposes.

Every module that consumes an LLM registers one or
more :class:`AiPurposeSpec` entries at module-load time. The
:class:`app.core.llm.registry` resolver asks this registry for the
spec matching a given purpose key (typically the consumer passes a
hard-coded key like ``"vision.extract"``).

The registry is intentionally a flat dict, not a SQL table:

- It is read-mostly: registrations happen at import time, lookups are
  per-request but cost O(1).
- It is process-local: replications / multi-worker setups do not
  need to sync purposes across processes.
- Persistence isn't useful: a purpose is a feature contract, not a
  user-facing entity.

Cross-module governance: registering the same key twice raises
``ValueError`` rather than silently overwriting. This makes conflicts
between two feature modules ship-blockers instead of running with a
shadowed registration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.llm.base import LlmRequest
from app.core.llm.enums import LlmCapability

__all__ = [
    'AiContractProbe',
    'AiPurposeSpec',
    'register_ai_purpose',
    'get_purpose',
    'all_purposes',
]


@dataclass(frozen=True)
class AiContractProbe:
    """A self-test for one purpose: a real call, judged the way production judges it.

    Testing a connection by listing models proves the credentials work. It does
    not prove the model can answer in the agreed shape — which is the thing
    that actually breaks when someone switches provider, and it breaks in the
    field rather than in Settings.

    The probe closes that gap, and it deliberately reuses the module's own
    request and parser. A simplified stand-in would be testing something other
    than what later fails, which is worse than not testing at all.
    """

    build_request: Callable[[], LlmRequest]
    """Build the same kind of request the feature sends in production."""

    validate: Callable[[str], object]
    """The feature's own parser. Raises when the answer is unusable."""

    read_back: Callable[[object], dict[str, Any]] | None = None
    """What the answer says, against what the probe knows to be true.

    ``validate`` answers "is this the agreed shape". That is a different
    question from "did the model read the picture", and a probe that draws
    its own reference material knows the second answer too — it wrote the
    values it is looking at. Without this, a model returning a well-formed
    ``{"name": "Milk"}`` for a carton labelled OAT DRINK passes exactly like
    one that read it, and the difference surfaces on the user's first
    product instead of in Settings.

    Core does not know what any purpose's reference material says, so the
    comparison belongs to the purpose. It returns a plain dict for the test
    payload to carry; the shape is the purpose's own. Optional: a purpose
    with nothing to compare against simply leaves it out.
    """


@dataclass(frozen=True)
class AiPurposeSpec:
    """Description of a single AI purpose.

    Attributes:
        key: globally unique identifier. Convention is
            ``"<owner_module>.<feature>"`` (e.g. ``"vision.extract"``,
            ``"recipes.text_parse"``). Namespaced so feature flags
            remain stable across module renames.
        capability: which :class:`LlmCapability` a connection must
            declare in order to be eligible to bind to this purpose.
            The runtime resolver refuses capability mismatches
            (``registry.get_client_for_purpose``).
        label_key: i18n key for the UI label. Convention: ``"<module>:ai.purposeLabel"``.
        description_key: i18n key for the help text.
        owner_module: feature owner. Attribution for the settings screen
            (the purpose is offered when the module is enabled). Bindings
            live per purpose key in
            ``Organization.settings.ai.defaults[<key>]``; the module-scoped
            ``ai_default_connection_id`` is the legacy home of choices made
            before per-purpose slots and still reads as a fallback. Keep
            the value aligned with the module's ``metadata.name`` (the
            registry doesn't enforce that today, but the data migration
            does).
        probe: optional :class:`AiContractProbe` used by the connection
            test to check that a model can actually serve this purpose,
            not merely that the key is accepted.
    """

    key: str
    capability: LlmCapability
    label_key: str
    description_key: str
    owner_module: str
    probe: AiContractProbe | None = None


_PURPOSES: dict[str, AiPurposeSpec] = {}


def register_ai_purpose(spec: AiPurposeSpec) -> None:
    """Register *spec* under ``spec.key``.

    Idempotent for the same spec (the module re-imports triggered by
    pytest workers / test reordering are common), loud on a real
    conflict — different module registering the same key still raises
    ``RuntimeError`` with both owners named (a mistake of the module's author,
    found at import time; no request can cause it).
    """
    existing = _PURPOSES.get(spec.key)
    if existing is not None:
        # Same spec re-registered (e.g. module re-imported by pytest) —
        # silently keep the first registration.
        if existing == spec:
            return
        raise RuntimeError(
            f'AI purpose {spec.key!r} already registered by '
            f'{existing.owner_module!r}; cannot also be registered by '
            f'{spec.owner_module!r}.'
        )
    _PURPOSES[spec.key] = spec


def get_purpose(key: str) -> AiPurposeSpec | None:
    """Return the spec registered under *key*, or None."""
    return _PURPOSES.get(key)


def all_purposes() -> list[AiPurposeSpec]:
    """Snapshot of all registered purposes.

    The returned list is a fresh copy — mutating it does not affect
    the registry's internal state. Pin-tested by
    ``test_returns_list_not_view``.
    """
    return list(_PURPOSES.values())
