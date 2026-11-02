"""DB primitive facade for module code.

The module safety validator (``app.core.module_safety.FORBIDDEN_IMPORT_PREFIXES``)
blocks direct ``app.database`` and ``app.models`` imports in modules that are
not in ``TRUSTED_CORE_MODULES`` (e.g. ``equipment``, ``nutrition``).  This
facade re-exports the small set of DB primitives those modules genuinely
need — declarative ``Base`` for their own models, and session/engine
factories for background workers and startup hooks. It marks which symbols
were meant to cross from Core into module code; it confers no isolation —
module trust is certification and the operator's responsibility, not
containment (``docs/adr/ADR-019-modules-are-certified-not-sandboxed.md``).

DI helpers (``get_db``, ``get_async_db``, ``require_permission`` …) live in
``app.core.deps``.  The split keeps ``deps`` minimal.

Note: live re-exports.  ``init_async_engine()`` rebinds names like
``AsyncSessionLocal`` and ``async_engine`` *inside* ``app.database`` after
this facade is loaded.  A plain ``from app.database import X`` would freeze
the old (None) value here forever, so we use PEP 562 ``__getattr__`` to
forward every access to the live value.  Callers should use
``db_facade.AsyncSessionLocal`` rather than ``from db_facade import ...``.
"""

from app.database import AsyncSession, Base


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Forward attribute access to the live ``app.database`` module."""
    if name in __all__:
        from app import database

        return getattr(database, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [  # noqa: F822 - re-exported via __getattr__
    'AsyncSession',
    'AsyncSessionLocal',
    'Base',
    'ProductsSessionLocal',
    'SessionLocal',
    'async_engine',
    'products_engine',
]
