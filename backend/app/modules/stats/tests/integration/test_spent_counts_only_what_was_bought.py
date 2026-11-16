"""The spent figure is what the organization paid for, not what it re-posted.

A production run puts its product on the shelf as a receipt layer worth the
ingredients it used, and putting ingredients back does the same. Summed with
the purchases, the grapes were counted once when bought and again when they
came out as wine, and the waste percentage read against the inflated total.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration


def _layer(
    org_id: UUID | None, template_id: UUID, total: str, *, internal: bool
) -> StockValuationLayer:
    value = Decimal(total)
    return StockValuationLayer(
        organization_id=org_id,
        product_template_id=template_id,
        quantity=Decimal('1'),
        remaining_qty=Decimal('1'),
        unit_cost=value,
        total_value=value,
        direction='IN',
        currency='USD',
        internal=internal,
    )


def test_spent_leaves_out_what_the_books_posted_to_themselves(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> None:
    template = ProductTemplate(name='Grapes', organization_id=test_user.organization_id)
    db_session.add(template)
    db_session.flush()
    db_session.add(
        _layer(test_user.organization_id, template.id, '60.00', internal=False)
    )
    db_session.add(
        _layer(test_user.organization_id, template.id, '50.00', internal=True)
    )
    db_session.commit()

    response = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['total_spent'] == 60.0
    assert sum(month['spent'] for month in data['monthly_trend']) == 60.0
