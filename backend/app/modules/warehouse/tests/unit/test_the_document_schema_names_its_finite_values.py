"""The document and order responses name the values they can carry.

``DocumentSchema.type`` / ``status`` and ``PurchaseOrderSchema.status`` were
declared as free text although only a closed set is ever written, so the
generated types gave every screen a ``string`` to narrow by hand — and let a
misspelt status compile.
"""

from __future__ import annotations

from typing import Any

from app.modules.purchase_orders.schemas import PurchaseOrderSchema
from app.modules.warehouse.models import DocumentStatus, DocumentType
from app.modules.warehouse.schemas import DocumentSchema


def _values(schema: dict[str, Any], field: str) -> set[str]:
    prop = schema['properties'][field]
    if '$ref' in prop:
        name = prop['$ref'].rsplit('/', 1)[-1]
        return set(schema['$defs'][name]['enum'])
    return set(prop['enum'])


def test_a_document_response_lists_its_types_and_statuses() -> None:
    schema = DocumentSchema.model_json_schema()
    assert _values(schema, 'type') == {t.value for t in DocumentType}
    assert _values(schema, 'status') == {s.value for s in DocumentStatus}


def test_a_purchase_order_response_lists_its_statuses() -> None:
    schema = PurchaseOrderSchema.model_json_schema()
    assert _values(schema, 'status') == {
        'DRAFT',
        'PENDING_APPROVAL',
        'CONFIRMED',
        'CANCELLED',
        'COMPLETED',
    }
