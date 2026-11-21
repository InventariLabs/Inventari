"""The journal's entry for a new asset names the module that owns the record.

An asset is a record of the product ledger, so its creation is written as a
product entry. The Target column calls it an asset from what the entry says
about its owner, not from a guess about its shape: the creation snapshot
carries the owning module beside the name.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.category import Category
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


@pytest.mark.integration
def test_a_new_asset_is_journaled_with_its_owning_module(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
    db_session: Session,
) -> None:
    response = client.post(
        '/api/v1/items',
        headers=eq_auth_headers,
        json={
            'name': 'Fresh Laptop',
            'location_id': str(eq_storage_location.id),
            'category_id': str(eq_category.id),
            'quantity': 1,
            'metadata': {'equipment': {'serial_number': 'SN-NEW'}},
        },
    )
    assert response.status_code in (200, 201), response.text

    db_session.expire_all()
    entry = db_session.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == eq_org.id,
            AuditLog.target_type == 'item',
            AuditLog.action == 'CREATE',
        )
    ).first()
    assert entry is not None and entry.snapshot is not None
    assert entry.snapshot['name'] == 'Fresh Laptop'
    assert entry.snapshot['module_name'] == 'equipment'
