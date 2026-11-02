"""Every stored secret can be moved to a new encryption key.

Until now a key change was a one-way door: no command rewrote what was
stored, so rotating SECRET_KEY on an install that never set ENCRYPTION_KEY —
which is every Docker install — made every SMTP password, AI key and webhook
secret unreadable. ``manage.py secrets reencrypt`` walks every place a secret
is stored and rewrites it under the current key; these tests start from values
sealed under SECRET_KEY alone, which is what an existing install has, and
check them through the strict readers after the old key is gone.
"""

from __future__ import annotations

import json

import pytest

from app.cli.commands_secrets import reencrypt_secrets_impl
from app.config import settings
from app.core.module_registry import module_registry
from app.models.ai_connection import AiConnection
from app.models.email_job import EmailJob
from app.modules.webhooks.models import WebhookEndpoint
from app.services import crypto_service
from app.services.crypto_service import (
    UndecryptableSecretError,
    decrypt_app_secret,
    decrypt_module_secret,
    encrypt_app_secret,
    encrypt_module_secret,
)

pytestmark = [pytest.mark.integration]

OLD_SIGNING = 'the-signing-key-every-install-started-with'
NEW_SIGNING = 'a-signing-key-rotated-after-a-token-leak!!'
NEW_KEY = 'the-encryption-key-the-administrator-set-now'
NEXT_KEY = 'and-the-one-after-that-a-year-later-on-again'

_SCHEMA = {
    'type': 'object',
    'properties': {
        'signing': {
            'type': 'object',
            'properties': {'token': {'type': 'string', 'format': 'secret'}},
        }
    },
}


@pytest.fixture
def keys(monkeypatch):
    def configure(*, secret: str, encryption: str = '', previous: str = '') -> None:
        monkeypatch.setattr(settings, 'SECRET_KEY', secret)
        monkeypatch.setattr(settings, 'ENCRYPTION_KEY', encryption)
        monkeypatch.setattr(settings, 'PREVIOUS_ENCRYPTION_KEY', previous)
        _clear()

    yield configure
    _clear()


def _clear() -> None:
    for cached in (
        crypto_service._get_fernet,
        crypto_service._previous_fernets,
        crypto_service._get_module_aead,
        crypto_service._previous_module_aeads,
    ):
        cached.cache_clear()


@pytest.fixture
def stored(db_session, test_household, keys, monkeypatch):
    """One secret in every place one is stored, sealed under SECRET_KEY alone."""
    webhooks = module_registry.get('webhooks')
    monkeypatch.setattr(webhooks, 'get_settings_schema', lambda: _SCHEMA)
    keys(secret=OLD_SIGNING)

    test_household.settings = {
        'smtp': {'password': encrypt_app_secret('smtp-password')},
        'llm': {'api_key': encrypt_app_secret('llm-key')},
        'module:webhooks': {
            'signing': {'token': encrypt_module_secret('webhooks', 'module-token')}
        },
    }
    rows = {
        'connection': AiConnection(
            organization_id=test_household.id,
            name='Reader',
            provider='openrouter',
            api_key_enc=encrypt_app_secret('connection-key'),
        ),
        'endpoint': WebhookEndpoint(
            organization_id=test_household.id,
            name='Receiver',
            url='https://example.com/hook',
            secret=encrypt_module_secret('webhooks', 'hmac-key'),
        ),
        'mail': EmailJob(
            to_email='someone@example.com',
            subject='Queued',
            html_content='<p>Queued</p>',
            smtp_config_enc=encrypt_app_secret(json.dumps({'password': 'override'})),
        ),
    }
    db_session.add_all(rows.values())
    db_session.commit()
    return test_household, rows


def _read_everything(db_session, org, rows) -> dict[str, str]:
    for row in (org, *rows.values()):
        db_session.refresh(row)
    return {
        'smtp': decrypt_app_secret(org.settings['smtp']['password']),
        'llm': decrypt_app_secret(org.settings['llm']['api_key']),
        'module': decrypt_module_secret(
            'webhooks', org.settings['module:webhooks']['signing']['token']
        ),
        'connection': decrypt_app_secret(rows['connection'].api_key_enc),
        'endpoint': decrypt_module_secret('webhooks', rows['endpoint'].secret),
        'mail': json.loads(decrypt_app_secret(rows['mail'].smtp_config_enc))[
            'password'
        ],
    }


EXPECTED = {
    'smtp': 'smtp-password',
    'llm': 'llm-key',
    'module': 'module-token',
    'connection': 'connection-key',
    'endpoint': 'hmac-key',
    'mail': 'override',
}


class TestMovingAnExistingInstallToItsOwnKey:
    def test_every_secret_reads_back_once_the_signing_key_rotates(
        self, db_session, stored, keys
    ):
        org, rows = stored
        keys(secret=OLD_SIGNING, encryption=NEW_KEY)

        report = reencrypt_secrets_impl(db_session)
        db_session.commit()

        assert report.rewritten == len(EXPECTED)
        assert report.unreadable == []
        # The old signing key is gone: only the new encryption key is left.
        keys(secret=NEW_SIGNING, encryption=NEW_KEY)
        assert _read_everything(db_session, org, rows) == EXPECTED

    def test_without_the_command_the_rotation_loses_them(
        self, db_session, stored, keys
    ):
        """What every install faced before: the same rotation, no rewrite."""
        org, rows = stored
        keys(secret=NEW_SIGNING, encryption=NEW_KEY)

        with pytest.raises((UndecryptableSecretError, PermissionError)):
            _read_everything(db_session, org, rows)

    def test_a_second_run_rewrites_nothing(self, db_session, stored, keys):
        keys(secret=OLD_SIGNING, encryption=NEW_KEY)
        reencrypt_secrets_impl(db_session)
        db_session.commit()

        assert reencrypt_secrets_impl(db_session).rewritten == 0


class TestRotatingTheEncryptionKeyItself:
    def test_the_previous_key_keeps_them_readable_until_the_rewrite(
        self, db_session, stored, keys
    ):
        org, rows = stored
        keys(secret=OLD_SIGNING, encryption=NEW_KEY)
        reencrypt_secrets_impl(db_session)
        db_session.commit()

        keys(secret=NEW_SIGNING, encryption=NEXT_KEY, previous=NEW_KEY)
        assert _read_everything(db_session, org, rows) == EXPECTED

        assert reencrypt_secrets_impl(db_session).rewritten == len(EXPECTED)
        db_session.commit()
        keys(secret=NEW_SIGNING, encryption=NEXT_KEY)
        assert _read_everything(db_session, org, rows) == EXPECTED


class TestAValueNoKeyOpens:
    def test_it_is_reported_and_left_as_it_is(self, db_session, stored, keys):
        org, rows = stored
        keys(secret='a-key-nobody-remembers-any-longer-at-all')
        lost = encrypt_app_secret('lost')
        rows['connection'].api_key_enc = lost
        db_session.commit()
        keys(secret=OLD_SIGNING, encryption=NEW_KEY)

        report = reencrypt_secrets_impl(db_session)
        db_session.commit()

        assert report.unreadable == [
            f'ai_connections.api_key_enc {rows["connection"].id}'
        ]
        db_session.refresh(rows['connection'])
        assert rows['connection'].api_key_enc == lost
