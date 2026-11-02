"""A tenant-isolation violation is not told to the client; the item limit still is.

Creating a record answered the organization's item limit by catching
``PermissionError`` and sending its message back as a 403. The limit was the
only ``PermissionError`` in that chain the route had in mind, but not the
only one it could meet: the chain runs the modules' interceptors, and the
scoped session a module writes through refuses a row of another organization
with a ``PermissionError`` too — one whose message names the model, the row's
organization and the session's. The route would have sent that to the client
as the reason for a refusal.

The guard now raises ``TenantIsolationError``, which is a defect in the
calling code rather than a refusal and which nothing maps: the client gets
the plain 500 every unhandled error gets, and the log keeps the detail. The
limit raises ``QuotaExceededError``, and the route answers it through the
canonical mapping, in the envelope it always had
(``test_the_item_limit_answers_both_doors.py``).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.context import ModuleContext
from app.core.exceptions import QuotaExceededError
from app.core.interceptors import ItemInterceptor, interceptor_pipeline
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.services.items._quota import check_item_quota_async

pytestmark = pytest.mark.integration


class _CrossingInterceptor(ItemInterceptor):
    """A module hook that writes a row of another organization through its scoped session."""

    def __init__(self, elsewhere: UUID) -> None:
        self.elsewhere = elsewhere

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        async with context.tenant_session(str(context.organization_id)) as scoped:
            scoped.add(
                ProductTemplate(organization_id=self.elsewhere, name='Elsewhere')
            )
        return data

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes


def test_a_tenant_violation_in_a_module_reaches_the_client_as_a_plain_500(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
) -> None:
    elsewhere = Organization(id=uuid.uuid4(), name='Another Household')
    db_session.add(elsewhere)
    db_session.commit()
    interceptor = _CrossingInterceptor(elsewhere.id)
    # The global handler answers the 500; the test client would otherwise
    # re-raise the error instead of showing what the client receives.
    quiet = TestClient(client.app, raise_server_exceptions=False)

    interceptor_pipeline.register_item_interceptor(interceptor)
    try:
        response = quiet.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Crossing',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )
    finally:
        interceptor_pipeline.unregister_item_interceptor(interceptor)

    assert response.status_code == 500, response.text
    assert response.json() == {
        'detail': {
            'code': 'INTERNAL_ERROR',
            'message': 'An internal error occurred',
        }
    }
    assert str(elsewhere.id) not in response.text


@pytest.mark.asyncio
async def test_the_item_limit_is_a_refusal_of_its_own(put_on_item_limit) -> None:
    organization_id = uuid.uuid4()
    put_on_item_limit(organization_id)

    with pytest.raises(QuotaExceededError):
        await check_item_quota_async(organization_id, MagicMock(spec=AsyncSession))
