"""Two configuration values that fail quietly, and now do not.

FRONTEND_URL builds every invitation, registration and password-reset link.
Left at its default in production nothing errors — the mails go out, pointing
at localhost, to people who cannot open them, and no log line says why the
invitations stopped working. It sat outside the production checklist that
already covers DATABASE_URL, REDIS_URL and SECRET_KEY.

SMTP without TLS is a legitimate setup for a relay on this host and a bad
surprise for anything else. Nothing said which one a deployment had.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.config import (
    frontend_url_is_deployable,
    settings,
    warn_if_frontend_url_is_local,
)
from app.services.email_service import warn_if_system_smtp_is_plaintext

pytestmark = pytest.mark.unit


class TestFrontendUrl:
    @pytest.mark.parametrize(
        'url',
        [
            'http://localhost:5173',
            'http://127.0.0.1:5173',
            'http://0.0.0.0:5173',
            'http://[::1]:5173',
            '',
        ],
    )
    def test_a_developer_machine_value_is_refused(self, url: str) -> None:
        assert frontend_url_is_deployable(url) is False

    @pytest.mark.parametrize(
        'url',
        ['https://inventari.example.com', 'http://inventari.internal:8080'],
    )
    def test_a_real_address_passes(self, url: str) -> None:
        assert frontend_url_is_deployable(url) is True


class TestFrontendUrlWarning:
    """The warning belongs to the server's startup, not to every import."""

    def _production(self, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
        monkeypatch.setattr(settings, 'DEBUG', False)
        monkeypatch.setattr(settings, 'TESTING', False)
        monkeypatch.setattr(settings, 'FRONTEND_URL', url)

    def test_a_production_server_building_links_to_localhost_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._production(monkeypatch, 'http://localhost:5173')

        assert warn_if_frontend_url_is_local() is True

    def test_a_production_server_with_a_real_address_says_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._production(monkeypatch, 'https://inventari.example.com')

        assert warn_if_frontend_url_is_local() is False

    def test_a_debug_server_says_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._production(monkeypatch, 'http://localhost:5173')
        monkeypatch.setattr(settings, 'DEBUG', True)

        assert warn_if_frontend_url_is_local() is False

    def test_importing_the_settings_prints_nothing_about_it(self) -> None:
        # Every manage.py command and lint run imports the settings; on a
        # stack with DEBUG=false the line used to head each of them.
        env = {
            'PATH': '/usr/bin:/bin',
            'DEBUG': 'false',
            'TESTING': 'false',
            'FRONTEND_URL': 'http://localhost:5173',
            'SECRET_KEY': 'a-real-secret-key-0123456789abcdef',
            'DATABASE_URL': 'postgresql://u:p@db/x',
            'REDIS_URL': 'redis://redis:6379/0',
            'FERNET_SALT': '0123456789abcdefXYZ',
        }
        result = subprocess.run(
            [sys.executable, '-c', 'import app.config'],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert 'FRONTEND_URL is' not in result.stdout + result.stderr


class TestSmtpWithoutTls:
    def test_an_unconfigured_relay_says_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, 'SMTP_HOST', None)

        assert warn_if_system_smtp_is_plaintext() is False

    def test_a_plaintext_port_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, 'SMTP_HOST', 'mail.example.com')
        monkeypatch.setattr(settings, 'SMTP_PORT', 25)
        monkeypatch.setattr(settings, 'SMTP_ENCRYPTION', None)

        assert warn_if_system_smtp_is_plaintext() is True

    @pytest.mark.parametrize('port', [587, 465])
    def test_the_two_ports_that_imply_tls_do_not(
        self, monkeypatch: pytest.MonkeyPatch, port: int
    ) -> None:
        monkeypatch.setattr(settings, 'SMTP_HOST', 'mail.example.com')
        monkeypatch.setattr(settings, 'SMTP_PORT', port)
        monkeypatch.setattr(settings, 'SMTP_ENCRYPTION', None)

        assert warn_if_system_smtp_is_plaintext() is False

    def test_an_explicit_setting_beats_the_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, 'SMTP_HOST', 'mail.example.com')
        monkeypatch.setattr(settings, 'SMTP_PORT', 587)
        monkeypatch.setattr(settings, 'SMTP_ENCRYPTION', 'none')

        assert warn_if_system_smtp_is_plaintext() is True
