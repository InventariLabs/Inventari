"""A shopping exclusion must name something the matching can key on.

The create door refused an empty name and nothing else: it stripped the name
only on the way to storage, so a name of spaces was saved as '' under the
empty matching key, and the list showed an exclusion that excludes nothing.
A zero-width space or a BOM does not even survive the strip it never meets —
the matching folds it to the same empty key, so the second such name,
whatever invisible character it carried, was answered with 409.
"""

from __future__ import annotations

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

EXCLUSIONS = '/api/v1/recipes/meal-plans/exclusions'


@pytest.mark.parametrize(
    'name',
    ['   ', '\u200b', '\ufeff', '\u200b\ufeff', '\u00a0'],
)
def test_a_name_that_folds_to_no_key_is_refused(
    client: TestClient, auth_headers: dict[str, str], name: str
) -> None:
    """Refused, with no row stored — so the next one is not a 409."""
    response = client.post(EXCLUSIONS, json={'name': name}, headers=auth_headers)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, response.text
    listed = client.get(EXCLUSIONS, headers=auth_headers).json()
    assert listed['total'] == 0, listed
