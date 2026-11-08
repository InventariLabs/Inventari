"""Returning a handover the organization does not have is refused in the reader's language.

The return looks the handover up through the shared organization-owned lookup,
which defaulted to English and handed that on: a Polish request was told
"Assignment not found". The lookup now leaves the language to the request,
for this path and for every other caller that does not name one.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.i18n.service import get_error_message


@pytest.mark.integration
def test_the_refusal_is_in_polish(
    client: TestClient, eq_auth_headers: dict[str, str]
) -> None:
    response = client.post(
        f'/api/v1/equipment/assignments/{uuid.uuid4()}/checkin',
        headers={**eq_auth_headers, 'Accept-Language': 'pl'},
        json={'checkin_condition': 'GOOD'},
    )

    assert response.status_code == 404, response.text
    assert response.json()['detail']['code'] == 'ASSIGNMENT_NOT_FOUND'
    assert response.json()['detail']['message'] == get_error_message(
        'assignment_not_found', 'pl'
    )
