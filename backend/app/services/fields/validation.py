"""Field value validation.

The new field types have richer value shapes than the legacy
primitives:

  - ``money``        value: ``{amount: number, currency: str}``
  - ``multi-select`` value: ``string[]`` (each element must be in field.options)

``validate_field_value(field, value)`` is the single helper that:
  1. Routes by field type.
  2. Enforces the value-shape contract.
  3. Raises :class:`FieldValueError` on failure with the offending key in the
     exception attributes for API-level diagnostics.

Storage note: this helper does NOT touch the database. It validates a Python
value (typically already pulled from / about to be written to
``Item.meta_data``). Callers (item create/update, scan, etc.) wrap
per-field values and call this once per field.
"""

from __future__ import annotations

import re as _re
from typing import Any

from app.core.exceptions import ServiceRejectionError
from app.schemas.category import CategoryFieldDefinition


class FieldValueError(ServiceRejectionError):
    """Raised when a field value violates the type-specific contract.

    A catalogued refusal, so the 400 handler answers it in the reader's
    language. Carries the offending ``field_key`` so API error responses can
    surface a useful per-field message.
    """

    def __init__(
        self,
        key: str,
        /,
        *,
        field: CategoryFieldDefinition,
        value: Any = None,
        options: list[str] | None = None,
    ) -> None:
        self.field_key = field.key
        # What a choice was refused against, for a door that words the
        # refusal itself (the import, in the reader's language).
        self.value = value
        self.options = options
        params: dict[str, Any] = {'field': field.label or field.key}
        if options is not None:
            params.update(value=value, options=', '.join(options))
        super().__init__(key, **params)


# Currency code: ISO 4217 shape (3 uppercase letters). We enforce the shape
# only; the exhaustive code list is a future enhancement.
_ISO_4217_RE = _re.compile(r'^[A-Z]{3}$')


def validate_field_value(field: CategoryFieldDefinition, value: Any) -> None:
    """Validate a single field value against its :class:`CategoryFieldDefinition`.

    Raises :class:`FieldValueError` on any contract violation. Returns
    ``None`` on success.
    """
    if value is None:
        if field.required:
            raise FieldValueError('custom_field_required', field=field)
        return  # None + optional is the "not set" sentinel — always valid.

    if field.type == 'multi-select':
        _validate_multi_select(field, value)
    elif field.type == 'money':
        _validate_money(field, value)
    elif field.type == 'select':
        _validate_select(field, value)
    # 'text', 'number', 'date', 'boolean', 'textarea', 'file' pass through;
    # pydantic / DB layer handles their primitive validation.


# ── Per-type validators ────────────────────────────────────────────────


def _validate_multi_select(field: CategoryFieldDefinition, value: Any) -> None:
    if not isinstance(value, list):
        raise FieldValueError('field_multi_select_shape', field=field)
    allowed = set(field.options or [])
    for element in value:
        if not isinstance(element, str):
            raise FieldValueError('field_multi_select_shape', field=field)
        if element not in allowed:
            raise FieldValueError(
                'field_option_not_allowed',
                field=field,
                value=element,
                options=sorted(allowed),
            )


def _validate_money(field: CategoryFieldDefinition, value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {'amount', 'currency'}:
        raise FieldValueError('field_money_shape', field=field)
    amount = value['amount']
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        raise FieldValueError('field_money_amount', field=field)
    currency = value['currency']
    if not isinstance(currency, str) or not _ISO_4217_RE.match(currency):
        raise FieldValueError('field_money_currency', field=field)


def _validate_select(field: CategoryFieldDefinition, value: Any) -> None:
    if not isinstance(value, str):
        raise FieldValueError('field_select_shape', field=field)
    if value not in (field.options or []):
        raise FieldValueError(
            'field_option_not_allowed',
            field=field,
            value=value,
            options=list(field.options or []),
        )


# ── Whole-meta_data orchestration ──────────────────────────────────────


#: The keys a category definition can carry for a column or a form field the
#: product itself owns. A definition under one of them restyles that field
#: (label, visibility); it is not a custom field a record has to fill.
_OWN_FIELD_KEYS = frozenset(
    {
        'name',
        'quantity',
        'unit',
        'brand',
        'description',
        'category_id',
        'expiry_date',
        'freeze_date',
        'shelf_location',
        'weight',
        'purchase_price',
        'barcode',
        'serial_number',
        'location_id',
    }
)


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def refuse_missing_required_fields(
    metadata: Any,
    field_definitions: list[dict[str, Any]] | None,
) -> None:
    """Refuse a new record that leaves a required custom field of its category empty.

    The add form has always stopped the reader at a required field; this is
    the same rule for the doors that have no form — the import and the API —
    so a category's "required" is a rule and not a hint of one screen. A field
    the category hides is never offered, so none can be asked for it, and a
    field the catalogue itself owns (``is_system``) is filled by the module
    that declared it.
    """
    values = metadata if isinstance(metadata, dict) else {}
    for definition in field_definitions or []:
        if not isinstance(definition, dict) or not definition.get('required'):
            continue
        key = definition.get('key')
        if (
            not key
            or key in _OWN_FIELD_KEYS
            or definition.get('is_system')
            or definition.get('visible', True) is False
        ):
            continue
        if not _is_filled(values.get(key)):
            raise ServiceRejectionError(
                'custom_field_required', field=definition.get('label') or key
            )


def validate_item_metadata_fields(
    metadata: Any,
    field_definitions: list[dict[str, Any]] | None,
) -> None:
    """Validate every ``metadata`` value against the matching field_definition.

    Called from the item create/update write paths to enforce the type-specific
    value contract declared on the item's category. ``metadata`` is the raw
    ``Item.meta_data`` dict; ``field_definitions`` is the category's definition
    list (as returned by CoreAPI / stored in JSONB — a list of plain dicts).

    Semantics (per the design spec's "advisory schema" principle):
      - Keys NOT declared in ``field_definitions`` are left untouched (open
        contract — module-namespaced data, ad-hoc custom fields, etc.).
      - Keys that ARE declared must satisfy their type's value-shape contract;
        a violation raises :class:`FieldValueError`.
      - A missing key is always valid (requiredness is enforced elsewhere).
      - ``metadata`` falsy (None / empty) is a no-op.
    """
    if not metadata or not field_definitions:
        return
    if not isinstance(metadata, dict):
        return  # malformed shape is not this helper's concern

    # Index the declared definitions by key. Each entry is a plain dict (as
    # stored in JSONB); coerce into a CategoryFieldDefinition to reuse the per-type
    # validators. Lenient construction (default type='text') so legacy defs
    # without an explicit type still validate as text (pass-through).
    by_key: dict[str, CategoryFieldDefinition] = {}
    for fd in field_definitions:
        if isinstance(fd, dict):
            key = fd.get('key')
            if key:
                by_key[key] = CategoryFieldDefinition.model_validate(fd)

    for key, value in metadata.items():
        field = by_key.get(key)
        if field is None:
            continue  # undeclared key — advisory, leave untouched
        validate_field_value(field, value)
