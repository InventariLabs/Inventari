"""Bridge legacy top-level date fields to namespaced meta_data locations.

The Core ``Item`` model is domain-neutral (no food/manufacturing columns), but
the public API still exposes ``freeze_date`` for backward compatibility. These
helpers route writes/reads through ``meta_data[namespace]`` so the Core model
stays clean while the API contract is preserved.

Part of keeping the core free of food-specific vocabulary: freeze_date and
(production_date).
"""

from datetime import date
from typing import Any

# Maps a legacy top-level field name to its meta_data namespace.
LEGACY_DATE_FIELDS: dict[str, str] = {
    'freeze_date': 'food',
    # 'production_date': 'manufacturing',  # not folded yet
}


def fold_legacy_dates_into_meta(item_data: dict[str, Any]) -> None:
    """Move legacy top-level date fields into ``meta_data[namespace]`` in place.

    ``date`` objects are serialised to ISO strings for JSONB storage. Called on
    the create/scan write paths where ``item_data`` is a plain dict.
    """
    meta = dict(item_data.get('meta_data') or {})
    changed = False
    for field, namespace in LEGACY_DATE_FIELDS.items():
        if field in item_data:
            value = item_data.pop(field)
            if value is not None:
                ns = dict(meta.get(namespace) or {})
                ns[field] = _to_iso(value)
                meta[namespace] = ns
            changed = True
    if changed:
        item_data['meta_data'] = meta


def merge_legacy_date_into_meta(
    current_meta: dict | None, field: str, value: Any
) -> dict | None:
    """Return a new ``meta_data`` dict with ``field`` merged into its namespace.

    Unlike ``fold_legacy_dates_into_meta`` this preserves all existing
    ``meta_data`` keys (used by the update path where ``meta_data`` must be
    merged, not replaced).
    """
    namespace = LEGACY_DATE_FIELDS.get(field)
    if namespace is None:
        return current_meta
    meta = dict(current_meta or {})
    ns = dict(meta.get(namespace) or {})
    if value is None:
        ns.pop(field, None)
    else:
        ns[field] = _to_iso(value)
    if ns:
        meta[namespace] = ns
    else:
        meta.pop(namespace, None)
    return meta


def legacy_date_in_meta(meta: dict | None, field: str) -> str | None:
    """The legacy date ``field`` as ``meta_data`` holds it, in ISO form.

    The read half of :func:`merge_legacy_date_into_meta`, for a writer that
    has to say what the date was before it merged a new one.
    """
    namespace = LEGACY_DATE_FIELDS.get(field)
    if namespace is None:
        return None
    return ((meta or {}).get(namespace) or {}).get(field)


def _to_iso(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
