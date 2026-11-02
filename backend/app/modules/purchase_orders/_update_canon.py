"""The partial-update canon (backend/AGENTS.md §2b) as executable shape.

Shared by every update endpoint in the module so the contract reads the
same four times.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.exceptions import catalogue_refusal


def refuse_named_nulls(data: BaseModel, not_clearable: set[str]) -> None:
    """Refuse a named null on a column that cannot be cleared.

    §2b: a key the payload omits means "leave the column alone", a named
    null on a nullable column means "clear it", and a named null on a NOT
    NULL column is a contract refusal — answered with 400 naming the
    field, never with a silent no-op the operator reads as success.
    """
    sent = data.model_fields_set
    attempts = sorted(f for f in not_clearable & sent if getattr(data, f) is None)
    if attempts:
        raise catalogue_refusal('field_cannot_be_cleared', fields=', '.join(attempts))
