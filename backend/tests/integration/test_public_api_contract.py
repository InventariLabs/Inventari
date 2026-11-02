"""Contract tests for CoreAPI public surface.

Validates that every public method on every ``Core*API`` namespace class:
1. Has a return type annotation (sig.return_annotation is not sig.empty)
2. Has no sync twin (no ``def foo`` alongside ``async def foo``)

This is a pure introspection test — no database or network required.
"""

from __future__ import annotations

import inspect
from collections import defaultdict

import pytest

from app.core.public_api import __all__ as public_api_all


def _get_all_core_api_classes() -> list[type]:
    """Return every class in ``__all__`` whose name starts with ``Core`` and ends with ``API``."""
    import app.core.public_api as mod

    classes = []
    for name in public_api_all:
        obj = getattr(mod, name)
        if isinstance(obj, type) and name.startswith('Core') and name.endswith('API'):
            classes.append(obj)
    return sorted(classes, key=lambda c: c.__name__)


def _public_methods(cls: type) -> list[tuple[str, inspect.Signature, bool]]:
    """Return non-dunder, non-underscore-prefixed methods of *cls*.

    Each entry is ``(name, signature, is_coroutine)``.
    """
    results: list[tuple[str, inspect.Signature, bool]] = []
    for attr_name in dir(cls):
        if attr_name.startswith('_'):
            continue
        attr = getattr(cls, attr_name, None)
        if not callable(attr):
            continue
        # Skip properties, classmethods, staticmethods — only inspect plain functions/methods
        if isinstance(attr, (property, classmethod, staticmethod)):
            continue
        sig = inspect.signature(attr)
        is_coro = inspect.iscoroutinefunction(attr)
        results.append((attr_name, sig, is_coro))
    return results


# ---------------------------------------------------------------------------
# Parametrised checks
# ---------------------------------------------------------------------------

ALL_CORE_API_CLASSES = _get_all_core_api_classes()


def _all_methods_flat():
    """Yield (class_name, method_name, signature, is_coroutine) for every public method."""
    for cls in ALL_CORE_API_CLASSES:
        for name, sig, is_coro in _public_methods(cls):
            yield pytest.param(
                cls.__name__, name, sig, is_coro, id=f'{cls.__name__}.{name}'
            )


@pytest.mark.integration
class TestCoreAPIReturnAnnotations:
    """Every public method on Core*API classes must have a return type annotation."""

    def test_all_methods_have_return_annotation(self):
        violations: list[str] = []
        for cls in ALL_CORE_API_CLASSES:
            for name, sig, _is_coro in _public_methods(cls):
                if sig.return_annotation is inspect.Signature.empty:
                    violations.append(f'{cls.__name__}.{name}')
        assert not violations, (
            'The following methods lack a return type annotation:\n'
            + '\n'.join(f'  - {v}' for v in violations)
        )


@pytest.mark.integration
class TestCoreAPISyncAsyncPairs:
    """No public method name should exist as both sync and async in the same class."""

    def test_no_sync_async_twins(self):
        violations: list[str] = []
        for cls in ALL_CORE_API_CLASSES:
            by_name: dict[str, list[bool]] = defaultdict(list)
            for name, _sig, is_coro in _public_methods(cls):
                by_name[name].append(is_coro)
            for method_name, coroutine_flags in by_name.items():
                if (
                    len(coroutine_flags) > 1
                    and any(coroutine_flags)
                    and not all(coroutine_flags)
                ):
                    violations.append(f'{cls.__name__}.{method_name}')
        assert not violations, (
            'The following methods exist as both sync and async in the same class:\n'
            + '\n'.join(f'  - {v}' for v in violations)
        )
