"""A refusal raised inside a Pydantic validator answers in the reader's language.

A validator's ``ValueError`` flies as a 422, an envelope the 400 handler never
sees, so its sentence reached a Polish reader as English prose with no claim
about its language. A validator that raises the keyed rejection gets the same
treatment the 400 envelope gives: the sentence is resolved from the catalogue
in the request language and the entry says which language that was.
"""

from __future__ import annotations

import pytest
from fastapi import status

pytestmark = pytest.mark.integration


def _register(client, lang: str | None = None, **overrides):
    payload = {
        'email': 'validator-probe@example.com',
        'password': 'Sup3rSecret',
        'full_name': 'Validator Probe',
    }
    payload.update(overrides)
    headers = {'Accept-Language': lang} if lang else {}
    return client.post('/api/v1/auth/register', json=payload, headers=headers)


def test_a_password_without_a_digit_is_refused_in_polish_with_the_language_named(
    client,
):
    response = _register(client, lang='pl', password='Abcdefgh')

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    error = response.json()['detail'][0]
    assert error['msg'] == 'Hasło musi zawierać co najmniej jedną cyfrę'
    assert error['lang'] == 'pl'
    assert error['loc'][-1] == 'password'


def test_the_same_refusal_in_english_names_english(client):
    response = _register(client, password='Abcdefgh')

    error = response.json()['detail'][0]
    assert error['msg'] == 'Password must contain at least one digit'
    assert error['lang'] == 'en'


def test_a_builtin_constraint_error_makes_no_language_claim_of_its_own(client):
    # Only the sentences the handler resolved from a key carry `lang`; the
    # pydantic constraint catalogue is a different mechanism with its own test.
    response = _register(client, lang='pl', password='x' * 200)

    assert 'lang' not in response.json()['detail'][0]
