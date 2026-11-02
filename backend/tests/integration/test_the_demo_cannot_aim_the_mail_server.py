"""On a public demo the mail server is the demo's own, and nobody can move it.

A demo publishes its administrator login, so every visitor is that
administrator: they can open the organization's email settings, store a host
and port of their choosing, and the test-email endpoint dials them at once —
from our address, at whatever machine and port they name. Mail already stored
on the organization was used the same way, and every message sent with it
bypassed the demo's Mailpit capture.

The instance now knows it is a demo (``INVENTARI_DEMO``, read through the
application's one settings object, and declared for the backend by
``docker-compose.demo.yml``). This file pins what that knowledge does: the
save is refused, and every send resolves to the system SMTP whatever the
organization row holds or the request body asks for.

The non-demo cases matter as much as the demo ones — a check that refuses
everything is not a lock, it is an outage — so the same two paths are pinned
to still use the stored settings where the instance is not a demo.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.services.crypto_service import decrypt_settings, encrypt_value
from app.services.email_service import EmailService

pytestmark = pytest.mark.integration

#: What a visitor would type to aim the demo server at a machine of theirs.
_VISITOR_SMTP = {
    'host': 'attacker.example',
    'port': 2525,
    'encryption': 'none',
    'user': 'stranger',
    'password': 'visitor-secret',
    'from_email': 'attacker@example.com',
    'from_name': 'Not Inventari',
}

#: The relay the demo stack pins the application to.
_SYSTEM_RELAY = {
    'SMTP_HOST': 'mailpit',
    'SMTP_PORT': 1025,
    'SMTP_ENCRYPTION': 'none',
    'SMTP_USER': 'demo',
    'SMTP_PASSWORD': 'demo',
}


def _declare_demo(monkeypatch: pytest.MonkeyPatch, *, demo: bool) -> None:
    """State what this instance is, rather than inherit the machine's answer."""
    monkeypatch.setattr('app.services.email_service.settings.INVENTARI_DEMO', demo)


def _state_the_system_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _SYSTEM_RELAY.items():
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)


def _mock_smtp(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Catch the connection instead of opening one."""
    server = MagicMock()
    server.__enter__.return_value = server
    smtp_cls = MagicMock(return_value=server)
    monkeypatch.setattr(smtplib, 'SMTP', smtp_cls)
    monkeypatch.setattr(
        smtplib,
        'SMTP_SSL',
        MagicMock(side_effect=AssertionError('opened a TLS connection')),
    )
    return smtp_cls


def _store_in_the_organization(db_session: Session, organization) -> None:
    """Write SMTP settings onto the row the way the settings screen would."""
    organization.settings = {
        **(organization.settings or {}),
        'smtp': {
            **_VISITOR_SMTP,
            'password': encrypt_value(_VISITOR_SMTP['password']),
        },
    }
    db_session.commit()


class TestTheSaveIsRefused:
    def test_a_demo_refuses_to_store_organization_smtp(
        self, client, auth_headers, db_session, test_household, monkeypatch
    ):
        _declare_demo(monkeypatch, demo=True)

        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'settings': {'smtp': _VISITOR_SMTP}},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'DEMO_SMTP_SETTINGS_LOCKED'
        assert 'demo' in detail['message'].lower()

        db_session.refresh(test_household)
        assert 'smtp' not in (test_household.settings or {})

    def test_an_instance_that_is_not_a_demo_still_stores_them(
        self, client, auth_headers, db_session, test_household, monkeypatch
    ):
        _declare_demo(monkeypatch, demo=False)

        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'settings': {'smtp': _VISITOR_SMTP}},
        )

        assert response.status_code == 200, response.text
        db_session.refresh(test_household)
        stored = (test_household.settings or {}).get('smtp', {})
        assert stored.get('host') == 'attacker.example'


class TestAMessageCannotBeAimed:
    def test_the_test_email_sends_through_the_system_relay_on_a_demo(
        self, client, auth_headers, db_session, test_household, monkeypatch
    ):
        """The visitor's own host never sees a connection.

        This is the exact abuse the demo closes: the form posts a host and
        port, the endpoint dials them immediately, and a stranger used that
        to probe machines from our address.
        """
        _declare_demo(monkeypatch, demo=True)
        _state_the_system_relay(monkeypatch)
        _store_in_the_organization(db_session, test_household)
        smtp_cls = _mock_smtp(monkeypatch)

        response = client.post(
            '/api/v1/organizations/my/test-email',
            headers=auth_headers,
            json=_VISITOR_SMTP,
        )

        assert response.status_code == 200, response.text
        host, port = smtp_cls.call_args.args[:2]
        assert (host, port) == ('mailpit', 1025)
        smtp_cls.return_value.login.assert_called_once_with('demo', 'demo')

    def test_settings_stored_on_the_organization_are_ignored_on_a_demo(
        self, db_session, test_household, monkeypatch
    ):
        """The row already holds a relay; the demo still uses its own.

        A demo database rebuilt from the seed never carries one, but a
        configuration saved before the instance became a demo — or written
        straight into the row — must not aim a message either.
        """
        _declare_demo(monkeypatch, demo=True)
        _state_the_system_relay(monkeypatch)
        _store_in_the_organization(db_session, test_household)
        stored = decrypt_settings(test_household.settings)['smtp']
        assert stored['host'] == 'attacker.example'
        smtp_cls = _mock_smtp(monkeypatch)

        EmailService.send_email(
            'someone@example.com', 'Subject', '<p>x</p>', smtp_config=stored
        )

        host, port = smtp_cls.call_args.args[:2]
        assert (host, port) == ('mailpit', 1025)
        smtp_cls.return_value.login.assert_called_once_with('demo', 'demo')

    def test_settings_stored_on_the_organization_are_used_off_a_demo(
        self, db_session, test_household, monkeypatch
    ):
        _declare_demo(monkeypatch, demo=False)
        _state_the_system_relay(monkeypatch)
        _store_in_the_organization(db_session, test_household)
        stored = decrypt_settings(test_household.settings)['smtp']
        smtp_cls = _mock_smtp(monkeypatch)

        EmailService.send_email(
            'someone@example.com', 'Subject', '<p>x</p>', smtp_config=stored
        )

        host, port = smtp_cls.call_args.args[:2]
        assert (host, port) == ('attacker.example', 2525)
        smtp_cls.return_value.login.assert_called_once_with(
            'stranger', 'visitor-secret'
        )
