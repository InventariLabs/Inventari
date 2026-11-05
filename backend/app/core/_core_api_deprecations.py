"""Deprecated core_api surface with removal expiry.

The public surface modules are allowed to build against is frozen in
``contracts_snapshot.json`` and ``core_api_snapshot.json``, and versioned
through ``inventari_min_version`` — but a floor only protects forward:
nothing tells a module author that the platform had REMOVED what they
used. Events had the full machinery (``_event_deprecations``); this is
the same machinery for the hundred-times-larger core_api surface.

**Removed surface that no builder outside the repository used leaves without
a window.** The quant table's picking reads, replaced by group-and-lot reads
while the table was still in place, left with the table (archived ``quantdrop01``),
and so did every other method that wrote it, read it or answered with its
row. ``CoreStockAPI.reserve_async`` went the same way: a reservation always
belongs to a document and its call without one was refused, and no published
release ever carried it. None of them waited for a window: a window protects
builders outside the repository, and these had none. They are gone from the
facade, and a unit test keeps them gone, naming what replaces each
(``tests/unit/test_core_api_deprecations.py``).

**The register stands empty today.** The machinery below is not dead weight:
the first deprecation registered after the platform goes public gets a real,
dated window again.

Every entry carries a ``removal_release``: a unit test compares it
against the backend version in ``pyproject.toml`` and fails once the
release is reached, forcing either removal or an explicit expiry bump.
A second test reads the ``.. deprecated::`` docstrings under
``app/core/public_api`` and fails when one of them has no entry here —
a deprecation without a deadline is a promise nobody can keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The release a fresh entry may name as its removal deadline: two minor
#: releases after the current one, the window CONTRACTS_STABILITY.md §2
#: promises a stable surface. An entry carries its own date; nothing here
#: moves when one lands.
REMOVAL_RELEASE = '0.13.0'


@dataclass(frozen=True)
class CoreApiDeprecation:
    qualifier: str
    replacement: str
    reason: str
    removal_release: str = REMOVAL_RELEASE


DEPRECATED_CORE_API: dict[str, CoreApiDeprecation] = {}


def get_deprecation(qualifier: str) -> CoreApiDeprecation | None:
    return DEPRECATED_CORE_API.get(qualifier)


def deprecated_facade_chains() -> dict[str, CoreApiDeprecation]:
    """Deprecated methods keyed by their facade chain (``file_storage.save``).

    Modules do not write ``CoreFileStorageAPI.save`` — they write
    ``core_api.file_storage.save``. The link between the two spellings is
    the attribute name on the facade, and only the live facade knows it
    reliably, so the map is derived from it rather than duplicated here.
    The facade import is deferred: the register is read by tooling that
    must not pay for the whole surface, and ``public_api`` does not import
    this module, so there is no cycle.
    """
    from app.core.public_api import core_api

    chains: dict[str, CoreApiDeprecation] = {}
    for ns_name in vars(core_api):
        namespace = getattr(core_api, ns_name)
        class_name = type(namespace).__name__
        for qualifier, deprecation in DEPRECATED_CORE_API.items():
            qualified_class, _, method = qualifier.rpartition('.')
            if qualified_class == class_name:
                chains[f'{ns_name}.{method}'] = deprecation
    return chains


def _deprecation_message(chain: str, deprecation: CoreApiDeprecation) -> str:
    return (
        f'core_api.{chain} is deprecated (removal in release '
        f'{deprecation.removal_release}): {deprecation.reason}. '
        f'Use {deprecation.replacement} instead.'
    )


def install_runtime_warnings(core_api_instance: object) -> int:
    """Wrap every registered deprecated method so calling it warns.

    The wrapper is bound to the *instance*, not the class: the method
    snapshot gate (``core_api_snapshot.json``) introspects class attributes,
    and a class-level wrapper would change what every gate and tool sees.
    Instance attributes are invisible to it. An entry whose method has
    already been removed is skipped — the snapshot's deprecation window
    allows exactly that pairing to drift for one release.

    Returns the number of methods wrapped.
    """
    import warnings
    from functools import wraps

    wrapped = 0
    for ns_name in vars(core_api_instance):
        namespace = getattr(core_api_instance, ns_name)
        class_name = type(namespace).__name__
        for qualifier, deprecation in DEPRECATED_CORE_API.items():
            qualified_class, _, method = qualifier.rpartition('.')
            if qualified_class != class_name:
                continue
            original = getattr(namespace, method, None)
            if original is None:
                continue

            # Synchronous wrapper, on purpose: a warning inside an async
            # function fires when the coroutine is awaited, not when it is
            # created — a caller that never awaited got a RuntimeWarning
            # about their own fire-and-forget instead of the deprecation.
            # This warns at the call site and hands the coroutine back for
            # the caller to await exactly as before.
            @wraps(original)
            def wrapper(
                *args: Any,
                _original: Any = original,
                _chain: str = f'{ns_name}.{method}',
                _dep: CoreApiDeprecation = deprecation,
                **kwargs: Any,
            ) -> Any:
                warnings.warn(
                    _deprecation_message(_chain, _dep),
                    DeprecationWarning,
                    stacklevel=2,
                )
                return _original(*args, **kwargs)

            setattr(namespace, method, wrapper)
            wrapped += 1
    return wrapped
