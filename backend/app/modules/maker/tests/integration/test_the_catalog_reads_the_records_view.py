"""The catalog's stock number is what the records say.

``get_stock_totals`` sums the records' view (``stock_quants_from_records``):
a record on the shelf is the catalog's number, with nothing else written
beside it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _recipe,
    _template,
)
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _catalog_stock(
    client: TestClient, headers: dict[str, str], recipe_name: str
) -> Decimal | None:
    listed = client.get('/api/v1/maker/recipes', headers=headers)
    assert listed.status_code == 200, listed.text
    items: list[dict[str, Any]] = listed.json()['items']
    row = next(item for item in items if item['name'] == recipe_name)
    return None if row['stock_qty'] is None else Decimal(str(row['stock_qty']))


def test_the_catalog_counts_the_records(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> None:
    ingredient = _template(db_session, mk_org, 'Flour on the records')
    output = _template(db_session, mk_org, 'Bread on the records')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    db_session.add(
        Item(
            organization_id=mk_org.id,
            name='Bread on the records',
            template_id=output.id,
            storage_location_id=mk_input_loc.id,
            quantity=Decimal('10'),
        )
    )
    anchor_pending_records(db_session)
    db_session.commit()

    # The record alone says 10: no movement, no layer, only the record.
    assert _catalog_stock(client, mk_auth_headers, 'One line') == Decimal('10')
