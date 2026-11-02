"""A nutrition value typed in by hand comes back on the record it was typed on.

The edit sheet saves manual figures to the record's product
(``PATCH /items/product-templates/{id}/nutrition``) and then reads the
record again. Both the sheet and the product page read what that record
carries, so the product's figures have to travel with it — this is the
server half of the round trip the frontend tests take from here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def test_the_saved_figures_travel_with_the_record(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> None:
    template = ProductTemplate(
        id=uuid.uuid4(), organization_id=test_user.organization_id, name='Cucumber'
    )
    db_session.add(template)
    db_session.flush()
    item = Item(
        id=uuid.uuid4(),
        organization_id=test_user.organization_id,
        storage_location_id=test_storage_location.id,
        name='Cucumber',
        template_id=template.id,
        quantity=Decimal('2'),
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()

    saved = client.patch(
        f'/api/v1/items/product-templates/{template.id}/nutrition',
        json={'nutrition_info': {'calories_kcal': 15, 'protein_g': 0.7}},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text

    record = client.get(f'/api/v1/items/{item.id}', headers=auth_headers)
    assert record.status_code == 200, record.text
    nutrition = record.json()['template']['meta_data']['nutrition']
    assert nutrition['calories_kcal'] == 15
    assert nutrition['protein_g'] == 0.7
