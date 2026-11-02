"""Built-in validation errors speak the language the request arrived in.

A Polish session that filled a field too long read pydantic's own English
sentence back — "String should have at most 255 characters" — because the
translated-error infrastructure only served the service layer's own
ValueErrors, and FastAPI's default 422 handler let the constraint checks
bypass it. The constraint types a person can act on now answer in the
session's language; anything the catalog does not carry keeps pydantic's
wording rather than a message nobody wrote.
"""

from __future__ import annotations

import pytest
from fastapi import status

pytestmark = pytest.mark.integration


def _register(client, lang: str | None = None, **overrides):
    payload = {
        'email': 'validation-probe@example.com',
        'password': 'Sup3rSecret',
        'full_name': 'Validation Probe',
    }
    payload.update(overrides)
    headers = {'Accept-Language': lang} if lang else {}
    return client.post('/api/v1/auth/register', json=payload, headers=headers)


def _detail_messages(response) -> list[str]:
    return [error['msg'] for error in response.json()['detail']]


def test_a_too_long_password_answers_in_polish(client):
    response = _register(client, lang='pl-PL,pl;q=0.9', password='x' * 200)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    messages = _detail_messages(response)
    assert 'Może mieć najwyżej 128 znaków' in messages
    # The payload shape is unchanged — only the sentences are translated.
    error = response.json()['detail'][0]
    assert error['type'] == 'string_too_long'
    assert error['loc'][-1] == 'password'


def test_the_same_request_answers_in_english_by_default(client):
    response = _register(client, password='x' * 200)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert 'Should have at most 128 characters' in _detail_messages(response)


def test_a_too_short_password_answers_in_polish(client):
    response = _register(client, lang='pl', password='abc')

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert 'Musi mieć co najmniej 8 znaków' in _detail_messages(response)


@pytest.mark.parametrize(
    ('min_length', 'noun'),
    [(1, 'znak'), (2, 'znaki'), (4, 'znaki'), (5, 'znaków'), (22, 'znaki')],
)
def test_a_short_string_limit_agrees_with_its_number_in_polish(min_length, noun):
    """The counted noun follows the number: 1 znak, 2 znaki, 5 znaków.

    The catalogue held one form ("znaków"), right for 5+ and wrong for every
    smaller limit — "Musi mieć co najmniej 1 znaków" reached the screen.
    """
    from app.i18n._validation import translate_validation_error

    message = translate_validation_error(
        {
            'type': 'string_too_short',
            'msg': 'String should have at least ... characters',
            'ctx': {'min_length': min_length},
        },
        lang='pl',
    )
    assert message == f'Musi mieć co najmniej {min_length} {noun}'


def test_a_long_string_limit_agrees_with_its_number_in_polish():
    from app.i18n._validation import translate_validation_error

    message = translate_validation_error(
        {
            'type': 'string_too_long',
            'msg': 'String should have at most ... characters',
            'ctx': {'max_length': 1},
        },
        lang='pl',
    )
    assert message == 'Może mieć najwyżej 1 znak'


def test_an_english_limit_of_one_uses_the_singular_noun():
    from app.i18n._validation import translate_validation_error

    message = translate_validation_error(
        {
            'type': 'string_too_short',
            'msg': 'String should have at least ... characters',
            'ctx': {'min_length': 1},
        },
        lang='en',
    )
    assert message == 'Should have at least 1 character'


def test_an_unknown_language_choice_answers_in_polish(client):
    response = _register(client, lang='pl', preferred_language='klingon')

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    messages = _detail_messages(response)
    # The enum's `ctx.expected` names the choices pydantic actually saw.
    assert any(msg.startswith('Dozwolone wartości:') for msg in messages)


def test_a_missing_field_answers_in_polish(client):
    response = client.post(
        '/api/v1/auth/register',
        json={'password': 'Sup3rSecret', 'full_name': 'No Email'},
        headers={'Accept-Language': 'pl'},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert 'To pole jest wymagane' in _detail_messages(response)


def test_an_error_type_outside_the_catalog_keeps_pydantics_wording(client):
    """The catalog is honest about what it does not carry.

    A type no template names falls through to pydantic's own sentence —
    untranslated, but precise — instead of a dropped or invented message.
    """
    from app.i18n._validation import translate_validation_error

    message = translate_validation_error(
        {'type': 'frobnicator_misaligned', 'msg': 'Frobnicator says no'},
        lang='pl',
    )
    assert message == 'Frobnicator says no'


def test_our_own_validator_messages_lose_the_pydantic_wrapper(client):
    response = _register(
        client,
        lang='pl',
        email='not-an-email-at-all',
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    messages = _detail_messages(response)
    assert 'Nieprawidłowy format email' in messages
    assert not any(msg.startswith('Value error, ') for msg in messages)
