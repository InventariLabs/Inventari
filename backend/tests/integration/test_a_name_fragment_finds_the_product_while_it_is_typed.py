"""The product pickers search as the name is typed, not on the whole name.

A formula's "add ingredient" box matched an existing product only on its
exact full name, so "Wosk" offered nothing while "Wosk sojowy" linked — and
a second product was created beside the first. The search the pickers call
matches any fragment of the name.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

URL = '/api/v1/items/product-templates'


def test_the_start_and_the_middle_of_a_name_both_find_the_product(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    pcs = db_session.execute(text("SELECT id FROM uoms WHERE symbol = 'pcs'")).first()
    assert pcs is not None
    created = client.post(
        URL, json={'name': 'Wosk sojowy', 'uom_id': str(pcs[0])}, headers=auth_headers
    )
    assert created.status_code == 201, created.text

    for fragment in ('Wo', 'Wosk', 'sojo', 'wosk SOJOWY'):
        found = client.get(URL, params={'search': fragment}, headers=auth_headers)
        assert found.status_code == 200, found.text
        assert [row['name'] for row in found.json()] == ['Wosk sojowy'], fragment
