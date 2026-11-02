"""On a public demo no password can be changed or reset.

Every e-mail a demo sends lands in the public Mailpit inbox, so a reset link
there would give the account to whoever opens it first, and a password change
is closed with it. Outside a demo both flows are pinned to behave as before.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.email_service import EmailService
from app.services.token_service import create_password_reset_token

pytestmark = pytest.mark.integration

_ME = '/api/v1/auth/me'
_REQUEST = '/api/v1/auth/password-reset/request'
_CONFIRM = '/api/v1/auth/password-reset/confirm'
_NEW_PASSWORD = 'NewStrong123'


def _declare_demo(monkeypatch: pytest.MonkeyPatch, *, demo: bool) -> None:
    monkeypatch.setattr('app.services.auth_service.settings.INVENTARI_DEMO', demo)


def _login(client: TestClient, email: str, password: str) -> int:
    return client.post(
        '/api/v1/auth/login', data={'username': email, 'password': password}
    ).status_code


def _capture_reset_mail(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    async def _capture(to_email: str, reset_link: str, **kwargs) -> bool:
        sent.append(reset_link)
        return True

    monkeypatch.setattr(EmailService, 'send_password_reset_email_async', _capture)
    return sent


def test_demo_refuses_a_password_change_and_keeps_the_stored_one(
    client: TestClient, auth_headers, test_user, monkeypatch
) -> None:
    _declare_demo(monkeypatch, demo=True)
    response = client.patch(
        _ME,
        json={'password': _NEW_PASSWORD, 'current_password': 'testpassword123'},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert _login(client, test_user.email, 'testpassword123') == 200
    assert _login(client, test_user.email, _NEW_PASSWORD) == 401


def test_demo_still_saves_the_name(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    _declare_demo(monkeypatch, demo=True)
    response = client.patch(_ME, json={'full_name': 'Visitor'}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['full_name'] == 'Visitor'


def test_demo_sends_no_reset_link(client: TestClient, test_user, monkeypatch) -> None:
    _declare_demo(monkeypatch, demo=True)
    sent = _capture_reset_mail(monkeypatch)
    response = client.post(_REQUEST, json={'email': test_user.email})
    assert response.status_code == 400
    assert sent == []


def test_demo_confirm_with_a_valid_token_changes_nothing(
    client: TestClient, test_user, monkeypatch
) -> None:
    _declare_demo(monkeypatch, demo=True)
    token = create_password_reset_token(test_user.id)
    response = client.post(
        _CONFIRM, json={'token': token, 'new_password': _NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert _login(client, test_user.email, 'testpassword123') == 200


def test_outside_a_demo_the_password_change_still_works(
    client: TestClient, auth_headers, test_user, monkeypatch
) -> None:
    _declare_demo(monkeypatch, demo=False)
    response = client.patch(
        _ME,
        json={'password': _NEW_PASSWORD, 'current_password': 'testpassword123'},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert _login(client, test_user.email, _NEW_PASSWORD) == 200


def test_outside_a_demo_the_reset_request_still_sends_the_link(
    client: TestClient, test_user, monkeypatch
) -> None:
    _declare_demo(monkeypatch, demo=False)
    sent = _capture_reset_mail(monkeypatch)
    response = client.post(_REQUEST, json={'email': test_user.email})
    assert response.status_code == 202
    assert len(sent) == 1
