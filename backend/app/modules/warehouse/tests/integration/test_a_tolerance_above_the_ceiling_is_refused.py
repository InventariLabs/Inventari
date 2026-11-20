"""An over-receipt tolerance above the ceiling is refused when it is saved.

The ceiling stops everyone, so a tolerance past it could never apply; saving
it with no word left the setting looking in force.
"""

from fastapi import status
from starlette.testclient import TestClient

URL = '/api/v1/modules/warehouse/settings'


def test_a_tolerance_above_a_set_ceiling_is_refused(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    resp = client.put(
        URL,
        headers=doc_auth_headers,
        json={
            'over_receipt_tolerance_percent': 50,
            'over_receipt_ceiling_percent': 20,
        },
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert 'tolerance (50%) is above the ceiling (20%)' in resp.text


def test_the_ceiling_alone_is_judged_against_the_saved_tolerance(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    saved = client.put(
        URL,
        headers=doc_auth_headers,
        json={
            'over_receipt_tolerance_percent': 30,
            'over_receipt_ceiling_percent': 0,
        },
    )
    assert saved.status_code == status.HTTP_200_OK, saved.text

    resp = client.put(
        URL, headers=doc_auth_headers, json={'over_receipt_ceiling_percent': 20}
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text


def test_no_ceiling_lets_any_tolerance_stand(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    resp = client.put(
        URL,
        headers=doc_auth_headers,
        json={
            'over_receipt_tolerance_percent': 50,
            'over_receipt_ceiling_percent': 0,
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.text
