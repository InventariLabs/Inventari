"""The stock-take schema's validator refusal answers in the reader's language.

``other_needs_a_note`` raises inside a Pydantic model validator, so the
refusal travels the 422 envelope. It is keyed, so a Polish counter reads a
Polish sentence and the entry says it is Polish.
"""

from typing import Any

import pytest
from starlette.testclient import TestClient


@pytest.mark.integration
def test_an_other_code_without_a_note_is_refused_in_polish(
    client: TestClient,
    auth_headers: dict[str, str],
    test_stock_take: Any,
) -> None:
    rows = client.get(
        f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
    ).json()['items']

    response = client.patch(
        f'/api/v1/stock-takes/{test_stock_take.id}/items/{rows[0]["id"]}/count',
        headers={**auth_headers, 'Accept-Language': 'pl'},
        json={'counted_quantity': 3, 'discrepancy_reason_code': 'OTHER'},
    )

    assert response.status_code == 422, response.text
    error = response.json()['detail'][0]
    assert error['msg'] == 'Powód rozbieżności jest wymagany'
    assert error['lang'] == 'pl'
