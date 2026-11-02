"""
Helpers for reading and writing module-owned namespaces inside
``ProductTemplate.meta_data`` (JSONB).

Design rules
------------
- Core stores ``meta_data`` but does not interpret its contents.
- Each module writes only under its own registered namespace key.
- Adding a new namespace requires a one-line change to ``ALLOWED_META_NAMESPACES``
  followed by a code review — intentional friction to prevent namespace pollution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from app.core.exceptions import ContractViolationError

if TYPE_CHECKING:
    from app.models.product_template import ProductTemplate


class HasMetaData(Protocol):
    """Anything carrying a ``meta_data`` mapping — an ORM row or a DTO.

    Reads only need the mapping, and callers legitimately hold either
    shape: writes still take a real ``ProductTemplate``, because only a
    persisted row can be written back.
    """

    @property
    def meta_data(self) -> dict[str, Any] | None: ...


# Registry of allowed namespace keys inside ProductTemplate.meta_data.
# To add a new one: append the key here and document which module owns it.
ALLOWED_META_NAMESPACES: frozenset[str] = frozenset(
    {
        'nutrition',  # nutrition module
        'specs',  # equipment module
        'traceability',  # traceability module (future)
        'library',  # library vertical (future)
    }
)


def get_template_namespace(template: HasMetaData, key: str) -> dict[str, Any] | None:
    """Return the module namespace payload stored at ``meta_data[key]``.

    Returns ``None`` if ``meta_data`` is empty or the key is absent.
    Does *not* validate the key against ``ALLOWED_META_NAMESPACES`` on reads —
    reads are always safe.
    """
    if not template.meta_data:
        return None
    return template.meta_data.get(key)


def set_template_namespace(
    template: ProductTemplate, key: str, value: dict[str, Any] | None
) -> None:
    """Write *value* into ``meta_data[key]``, replacing any previous content.

    Passing ``value=None`` removes the key from ``meta_data``.

    Raises ``ContractViolationError`` for unregistered namespace keys to prevent silent
    namespace pollution.
    """
    if key not in ALLOWED_META_NAMESPACES:
        raise ContractViolationError(
            f"Unknown meta_data namespace: '{key}'. "
            f'Register it in ALLOWED_META_NAMESPACES first. '
            f'Known namespaces: {sorted(ALLOWED_META_NAMESPACES)}'
        )
    payload = dict(template.meta_data or {})
    if value is None:
        payload.pop(key, None)
    else:
        payload[key] = value
    template.meta_data = payload or None


# ---------------------------------------------------------------------------
# Nutrition convenience helpers (owned by nutrition module)
# ---------------------------------------------------------------------------


def get_template_nutrition(template: HasMetaData) -> dict[str, Any] | None:
    """Return the nutrition payload for *template*, or ``None`` if absent."""
    return get_template_namespace(template, 'nutrition')


def set_template_nutrition(
    template: ProductTemplate, nutrition: dict[str, Any] | None
) -> None:
    """Write nutrition data into ``meta_data['nutrition']``.

    Passing ``None`` removes the nutrition key without affecting other namespaces.
    """
    set_template_namespace(template, 'nutrition', nutrition)
