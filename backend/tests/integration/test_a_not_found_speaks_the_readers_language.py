"""A 404 speaks the reader's language even where the call names none.

``NotFoundException`` took ``lang='en'`` by default, so every call site that
did not pass the request language — 83 of them across the routers — answered
a Polish session in English. The class now reads the request language itself.
"""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_a_missing_profile_is_reported_in_polish_to_a_polish_reader(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # The profile router raises ``NotFoundException('profile')`` with no
    # language: the request's own is the only one it can speak.
    response = client.get(
        '/api/v1/profiles/no-such-profile',
        headers={**auth_headers, 'Accept-Language': 'pl'},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.text
    assert response.json()['detail'] == {
        'code': 'PROFILE_NOT_FOUND',
        'message': 'Profil nie został znaleziony',
    }


@pytest.mark.integration
def test_an_english_reader_keeps_the_english_sentence(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(
        '/api/v1/profiles/no-such-profile',
        headers={**auth_headers, 'Accept-Language': 'en'},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.text
    assert response.json()['detail']['message'] == 'Profile not found'
