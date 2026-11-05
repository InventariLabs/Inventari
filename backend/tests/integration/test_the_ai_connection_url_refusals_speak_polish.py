"""A base URL the AI-connection guard refuses reads Polish on a Polish screen.

The URL guard raises keyed refusals, and the unit tests pin the keys. What a
reader sees is the 400 envelope the global handler builds around the key, so
these tests ask the real endpoint with ``Accept-Language: pl`` and assert the
sentence and the machine code. The webhook door never reaches these two
causes (its schema refuses them first), so the AI-connection door is where
they are exercised end to end.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}


def _create(client, auth_headers, base_url: str):
    return client.post(
        '/api/v1/ai-connections',
        json={
            'name': 'Refused address',
            'provider': 'openrouter',
            'api_key': 'sk-or-plaintext',
            'api_base_url': base_url,
        },
        headers={**auth_headers, **POLISH},
    )


def test_a_non_http_scheme_is_refused_in_polish(client, auth_headers):
    response = _create(client, auth_headers, 'ftp://example.com/v1')

    assert response.status_code == 400
    assert response.json()['detail'] == {
        'code': 'LLM_BASE_URL_SCHEME',
        'message': 'Adres połączenia AI musi używać http albo https.',
        'lang': 'pl',
    }


def test_an_address_without_a_host_is_refused_in_polish(client, auth_headers):
    response = _create(client, auth_headers, 'https:///v1')

    assert response.status_code == 400
    assert response.json()['detail'] == {
        'code': 'LLM_BASE_URL_NO_HOSTNAME',
        'message': 'Adres połączenia AI musi zawierać nazwę hosta.',
        'lang': 'pl',
    }
