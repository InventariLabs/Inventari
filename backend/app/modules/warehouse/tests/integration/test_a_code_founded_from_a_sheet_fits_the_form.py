"""A SKU the opening-stock sheet founds a product with fits the product form.

The sheet is the other door a code enters the catalogue by: it is stored
trimmed and upper-case, and a code the form cannot hold refuses its row.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _upload(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    code: str,
) -> Any:
    sheet = pd.DataFrame([{'Name': 'Opening lamp', 'Code': code, 'Qty': '2'}])
    return client.post(
        '/api/v1/warehouse/import/opening-stock',
        files={'file': ('opening.csv', sheet.to_csv(index=False), 'text/csv')},
        data={
            'target_location_id': str(location.id),
            'mapping_json': json.dumps(
                {'name': 'Name', 'sku': 'Code', 'quantity': 'Qty'}
            ),
        },
        headers=headers,
    )


def _codes(db: Session) -> list[str | None]:
    db.expire_all()
    return list(
        db.scalars(
            select(ProductTemplate.sku).where(ProductTemplate.name == 'Opening lamp')
        )
    )


class TestASkuOnTheOpeningStockSheet:
    def test_it_is_stored_in_the_shape_the_form_holds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        response = _upload(client, doc_auth_headers, doc_target_location, ' lamp-9 ')

        assert response.status_code == 200, response.text
        assert _codes(db_session) == ['LAMP-9']

    def test_a_code_the_form_cannot_hold_refuses_the_row(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        response = _upload(client, doc_auth_headers, doc_target_location, 'lamp.9')

        assert 'lamp.9' in response.text, response.text
        assert 'SKU may contain only' in response.text
        assert _codes(db_session) == []
