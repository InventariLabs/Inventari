"""An unreadable secret answers for itself in every path that meets it.

The rebind backfill promised to report values it cannot read and leave
them stored — but its arc caught only PermissionError, so the typed
"unreadable" error sailed over it and the command died mid-walk instead
of reporting. And the org SMTP password, read through the lenient
settings walk, arrived at the mail path as an empty string: the
administrator learned nothing about why mail stopped while the host,
user and masked password all still sat in the form. The typed error is
the reason; these tests pin it reaching both surfaces.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.services import crypto_service


def _unreadable(value: str) -> str:
    """*value* with one character deep in its ciphertext replaced: a
    rotation, in effect. The shape stays fernet-shaped — only the key that
    would open it is gone."""
    position = len(value) - 8
    replacement = 'A' if value[position] != 'A' else 'B'
    return f'{value[:position]}{replacement}{value[position + 1 :]}'


class TestTheRebindBackfillArc:
    def test_an_unreadable_value_is_reported_not_fatal(self, monkeypatch):
        """The typed unreadable error lands in the report, next to the
        PermissionError the arc already caught — and the walk continues."""
        from app.cli import commands_backfill as cb
        from app.services.crypto_service import UndecryptableSecretError

        class _Schema:
            pass

        class _Module:
            def get_settings_schema(self):
                return _Schema()

        monkeypatch.setattr(
            'app.core.module_registry.module_registry',
            type('R', (), {'get': staticmethod(lambda name: _Module())}),
        )
        monkeypatch.setattr(
            'app.core.settings_validator.iter_secret_paths',
            lambda schema: iter([('smtp', 'password')]),
        )
        monkeypatch.setattr(
            'app.services.crypto_service.decrypt_module_secret',
            lambda name, value: (_ for _ in ()).throw(
                UndecryptableSecretError('rotated')
            ),
        )

        values = {'smtp': {'password': 'enc:broken'}}

        rebound, already, unreadable = cb._rebind_namespace(values, 'some_module')

        assert (rebound, already) == (0, 0)
        assert unreadable == ['some_module.smtp.password']
        # left exactly as stored
        assert values['smtp']['password'] == 'enc:broken'


class TestTheOrgSmtpPasswordReadsStrictly:
    async def test_an_unreadable_password_logs_the_reason_and_reads_empty(
        self,
        real_async_db_session: Any,
        async_test_household: Any,
        caplog: pytest.LogCaptureFixture,
    ):
        """The mail path acts on the password, so the leaf is read strictly
        and downgraded HERE: the log carries the reason an administrator
        can act on — the settings walk alone would only say 'empty'."""
        from sqlalchemy import text

        from app.services.auth_service import AuthService

        org = async_test_household
        org.settings = {
            'smtp': {
                'host': 'smtp.example.com',
                'user': 'mailer@example.com',
                'password': _unreadable(crypto_service.encrypt_value('real-password')),
            }
        }
        await real_async_db_session.execute(
            text('SELECT 1')
        )  # keep the session warm for the flush below
        real_async_db_session.add(org)
        await real_async_db_session.commit()

        with caplog.at_level(logging.WARNING, logger='app.services.auth_service'):
            config = await AuthService.get_org_smtp_config_async(
                real_async_db_session, org.id
            )

        assert config is not None
        assert config['host'] == 'smtp.example.com'
        assert config['password'] == ''
        assert any(
            'SMTP password cannot be decrypted' in record.message
            and 're-entered' in record.message
            for record in caplog.records
        ), [r.getMessage() for r in caplog.records]
