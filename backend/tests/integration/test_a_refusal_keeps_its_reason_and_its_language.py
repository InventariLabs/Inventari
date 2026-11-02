"""A refusal keeps the reason it was raised with, and the reader's language.

Two families lost it. A router that caught a keyed refusal and answered 409
under one fixed code of its own (the approvals engine's ``APPROVAL_ERROR``)
made two different reasons read the same to a client. And a handful of
``ValidationException`` raises carried an English sentence under
``VALIDATION_ERROR``: a Polish reader changing a password saw an English
sentence and the client had nothing to branch on.

The assertions are equalities on the code and the Polish text, not status
codes: a call site reverted to its literal still answers the same status.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictException
from app.i18n import MAINTAINED_LANGUAGES
from app.i18n.service import get_error_message
from app.models.user import User
from app.modules.approvals import _documents_router
from app.modules.approvals.exceptions import ApprovalError
from app.modules.purchase_orders import _service_approval

pytestmark = pytest.mark.integration

NEW_KEYS = {
    'ingredient_defaults_unreadable_file': {'detail': 'x'},
    'onboarding_modules_not_offered': {'profile': 'p', 'modules': 'm'},
    'location_chain_step_incomplete': {},
    'current_password_incorrect': {},
    'storage_own_parent': {},
    'template_not_builtin_copy': {},
    'smtp_config_invalid': {'reason': 'r'},
    'module_needs_newer_platform': {'module': 'm', 'required': '9', 'current': '1'},
}


def test_a_wrong_current_password_is_refused_in_polish_under_its_own_code(
    client: TestClient, auth_headers: dict, test_user: User
) -> None:
    response = client.patch(
        '/api/v1/auth/me',
        json={'password': 'Sup3rSecret!', 'current_password': 'not-the-password'},
        headers={**auth_headers, 'Accept-Language': 'pl'},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json()['detail']
    assert detail['code'] == 'CURRENT_PASSWORD_INCORRECT'
    assert detail['field'] == 'current_password'
    assert detail['message'] == 'Obecne hasło jest nieprawidłowe'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('action', 'engine_call', 'status'),
    [
        ('request_purchase_order_approval', 'request_approval', 'DRAFT'),
        ('approve_purchase_order', 'approve_stage', 'PENDING_APPROVAL'),
        ('reject_purchase_order', 'reject_request', 'PENDING_APPROVAL'),
    ],
)
async def test_a_purchase_order_approval_conflict_answers_the_refusals_code(
    monkeypatch: pytest.MonkeyPatch, action: str, engine_call: str, status: str
) -> None:
    async def refuse(*_args, **_kwargs):
        raise ApprovalError('approval_workflow_needs_stage')

    async def active(*_args, **_kwargs):
        return SimpleNamespace(id=uuid4())

    api = _service_approval.approvals_api
    monkeypatch.setattr(api, engine_call, refuse)
    monkeypatch.setattr(api, 'find_active_request', active)
    po = SimpleNamespace(id=uuid4(), status=status)

    with pytest.raises(ConflictException) as caught:
        await getattr(_service_approval, action)(None, uuid4(), po, uuid4())

    assert caught.value.status_code == 409
    assert caught.value.detail['code'] == 'APPROVAL_WORKFLOW_NEEDS_STAGE'


def test_an_unreadable_defaults_file_is_refused_in_polish_under_its_own_code(
    client: TestClient, auth_headers: dict
) -> None:
    response = client.post(
        '/api/v1/recipes/ingredient-defaults/import',
        files={'file': ('defaults.json', b'{not json', 'application/json')},
        headers={**auth_headers, 'Accept-Language': 'pl'},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json()['detail']
    assert detail['code'] == 'INGREDIENT_DEFAULTS_UNREADABLE_FILE'
    assert detail['message'].startswith('Nie udało się odczytać pliku: ')


@pytest.mark.parametrize('steps', [[{'name': ' '}, {'name': 'Shelf'}], [{'name': ''}]])
def test_a_location_chain_step_without_id_or_name_is_refused_in_polish(
    client: TestClient, auth_headers: dict, steps: list[dict]
) -> None:
    response = client.post(
        '/api/v1/locations/hierarchy',
        json={'steps': steps},
        headers={**auth_headers, 'Accept-Language': 'pl'},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json()['detail']
    assert detail['code'] == 'LOCATION_CHAIN_STEP_INCOMPLETE'
    assert (
        detail['message']
        == 'Każdy krok łańcucha miejsc wymaga identyfikatora lub nazwy.'
    )


@pytest.mark.parametrize('key', sorted(NEW_KEYS))
def test_every_new_key_is_translated_in_every_maintained_language(key: str) -> None:
    english = get_error_message(key, 'en', **NEW_KEYS[key])
    assert english != key
    for lang in MAINTAINED_LANGUAGES:
        if lang == 'en':
            continue
        assert get_error_message(key, lang, **NEW_KEYS[key]) != english, (key, lang)


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['approve_purchase_order', 'reject_purchase_order'])
async def test_a_purchase_order_without_a_pending_request_answers_its_own_code(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    async def none_active(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        _service_approval.approvals_api, 'find_active_request', none_active
    )
    po = SimpleNamespace(id=uuid4(), status='PENDING_APPROVAL')

    with pytest.raises(ConflictException) as caught:
        await getattr(_service_approval, action)(None, uuid4(), po, uuid4())

    assert caught.value.status_code == 409
    assert caught.value.detail['code'] == 'PO_NO_PENDING_APPROVAL_REQUEST'


def test_a_document_without_a_pending_request_answers_its_own_code() -> None:
    error = _documents_router._no_pending_request()

    assert error.status_code == 409
    assert error.detail['code'] == 'DOCUMENT_NO_PENDING_APPROVAL_REQUEST'
