"""A secret one module saved must not read back as another module's.

The binding was built and tested and then nobody used it: every real
write went through the app-wide helper, including the one whose docstring
said "modules use this instead of reaching into the crypto service" while
producing exactly what reaching into the crypto service produces. The
measured consequence was that a key saved through the settings UI could
be read by naming any module at all.

These tests come at it from the outside — the settings write path a
module actually uses, and every read path that exists — rather than from
the crypto primitives, which were never the broken part.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.public_api import core_api
from app.services.crypto_service import (
    UndecryptableSecretError,
    decrypt_module_secret,
    decrypt_value_lenient,
    encrypt_module_secret,
    encrypt_value,
)

pytestmark = [pytest.mark.integration]


class TestTheModuleFacingWrite:
    def test_it_binds(self):
        stored = core_api.settings.encrypt_secret('module_a', 'A-SECRET')

        assert decrypt_module_secret('module_a', stored) == 'A-SECRET'

    def test_another_module_is_refused(self):
        stored = core_api.settings.encrypt_secret('module_a', 'A-SECRET')

        with pytest.raises(PermissionError):
            decrypt_module_secret('module_b', stored)

    def test_the_app_wide_reader_gets_nothing_usable(self):
        """The app-wide reader answers for the whole settings blob, so it
        takes the lenient reader: an unreadable value renders as empty —
        never as the secret."""
        stored = core_api.settings.encrypt_secret('module_a', 'A-SECRET')

        assert decrypt_value_lenient(stored) == ''

    def test_it_is_idempotent(self):
        once = core_api.settings.encrypt_secret('module_a', 'A-SECRET')
        twice = core_api.settings.encrypt_secret('module_a', once)

        assert decrypt_module_secret('module_a', twice) == 'A-SECRET'


class TestTheAppWideWrite:
    def test_it_says_so_in_its_name(self):
        """The installation's own credentials have their own name.

        It binds nothing and is supposed to: the SMTP password is read by
        the core mailer, not by a module. The name is the point — the old
        one (``encrypt_secret``) claimed to be the module helper while
        doing exactly this. It lives in ``crypto_service`` rather than on
        the module-facing facade, so a module cannot reach it through
        ``core_api`` at all, and the architecture lint refuses the routes
        that remain.
        """
        from app.services.crypto_service import (
            decrypt_app_secret,
            encrypt_app_secret,
        )

        stored = encrypt_app_secret('SMTP-PASS')

        assert decrypt_app_secret(stored) == 'SMTP-PASS'

    def test_it_is_not_on_the_module_facade(self):
        assert not hasattr(core_api.settings, 'encrypt_app_secret')


class TestValuesWrittenBeforeBinding:
    def test_they_still_read(self):
        """Nothing stored earlier becomes unreadable the day this ships."""
        legacy = encrypt_value('OLD-VALUE')

        assert decrypt_module_secret('any_module', legacy) == 'OLD-VALUE'

    def test_they_are_not_isolated_and_that_is_visible(self):
        # Deliberately recorded: a legacy value reads under any name, which
        # is exactly why the one-time rebind exists.
        legacy = encrypt_value('OLD-VALUE')

        assert decrypt_module_secret('module_a', legacy) == 'OLD-VALUE'
        assert decrypt_module_secret('module_b', legacy) == 'OLD-VALUE'


class TestTheSettingsRoundTrip:
    """Through the API a module really uses, not through the primitives."""

    @pytest.mark.asyncio
    async def test_a_saved_secret_reads_back_for_its_owner(self, real_async_db_session):
        from app.models import Organization

        org = Organization(
            id=uuid.uuid4(),
            name=f'secret-test-{uuid.uuid4().hex[:8]}',
            settings={},
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await core_api.settings.set_bulk_async(
            real_async_db_session,
            org.id,
            'module_a',
            {'api_key': encrypt_module_secret('module_a', 'ROUND-TRIP')},
        )
        await real_async_db_session.flush()

        value = await core_api.settings.get_decrypted_async(
            real_async_db_session, org.id, 'module_a', 'api_key'
        )
        assert value == 'ROUND-TRIP'

    @pytest.mark.asyncio
    async def test_the_same_value_is_refused_to_another_module(
        self, real_async_db_session
    ):
        from app.models import Organization

        org = Organization(
            id=uuid.uuid4(),
            name=f'secret-test-{uuid.uuid4().hex[:8]}',
            settings={},
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        stored = encrypt_module_secret('module_a', 'ROUND-TRIP')
        # Module B's namespace, holding a value bound to A: the shape a
        # hostile module would have to produce to read someone else's key.
        await core_api.settings.set_bulk_async(
            real_async_db_session, org.id, 'module_b', {'api_key': stored}
        )
        await real_async_db_session.flush()

        with pytest.raises(PermissionError):
            await core_api.settings.get_decrypted_async(
                real_async_db_session, org.id, 'module_b', 'api_key'
            )


class TestAMarkerEditedByHand:
    """A bound value whose ``enc:mod1:`` marker was edited reads today as an
    empty string: the mangled shape falls into the legacy branch,
    :func:`decrypt_value` cannot open it, and the log tells an
    administrator to rotate FERNET_SALT — exactly the wrong diagnosis for a
    row somebody rewrote in the table, and the delivery keeps going with a
    signature computed over an empty key. A value that still carries a
    sealed body but no readable marker is a refusal, not a silence; the
    legacy shapes a legitimate old row can have stay readable below."""

    @staticmethod
    def _bound() -> str:
        return encrypt_module_secret('module_a', 'A-SECRET')

    def test_a_marker_renamed_to_another_module_refuses(self):
        tampered = self._bound().replace('enc:mod1:', 'enc:mod_b:', 1)

        with pytest.raises(PermissionError):
            decrypt_module_secret('module_b', tampered)

    def test_an_uppercased_marker_refuses(self):
        tampered = self._bound().replace('enc:mod1:', 'enc:MOD1:', 1)

        with pytest.raises(PermissionError):
            decrypt_module_secret('module_a', tampered)

    def test_a_stripped_marker_refuses(self):
        tampered = 'enc:' + self._bound()[len('enc:mod1:') :]

        with pytest.raises(PermissionError):
            decrypt_module_secret('module_a', tampered)

    def test_the_legacy_suffix_format_still_reads(self):
        """``enc:<fernet>:<label>`` — the label sat outside the cipher and
        authenticated nothing, so the shape must keep reading under any
        name; the marker rule must not swallow it."""
        suffix = encrypt_value('OLD-VALUE') + ':springfield'

        assert decrypt_module_secret('module_a', suffix) == 'OLD-VALUE'

    def test_junk_that_was_never_a_secret_raises(self):
        """Short garbage is not shaped like anything: the strict reader
        answers "cannot read it" — the one answer that is not a mistake
        for a legally empty secret."""
        with pytest.raises(UndecryptableSecretError):
            decrypt_module_secret('module_a', 'enc:mod_b')

    def test_the_webhook_reader_names_the_refusal(self):
        """A tampered row must not sign anything, and the delivery path now
        refuses the attempt outright rather than skipping just the signature
        — so the exception has to be one it catches."""
        from app.modules.webhooks._webhook_constants import decrypt_secret
        from app.modules.webhooks.webhook_service import encrypt_secret

        tampered = encrypt_secret('hmac-key').replace('enc:mod1:', 'enc:MOD1:', 1)

        with pytest.raises(PermissionError):
            decrypt_secret(tampered)

    def test_a_stripped_marker_reads_through_when_the_nonce_looks_like_a_token(
        self,
    ):
        """The chance both docstrings name, constructed rather than waited for.

        A sealed body whose first byte is 0x80 has the shape of a Fernet
        token, so with the marker stripped the edited-marker rule cannot see
        the edit and the value reads as empty — a wrong silence, not a wrong
        refusal. The nonce is random, so the rate is about one body in 256
        (measured: 12 of 3000); this test pins the shape.
        """
        import base64

        sealed = encrypt_module_secret('module_a', 'x' * 29)
        body = sealed[len('enc:mod1:') :]
        raw = base64.urlsafe_b64decode(body)
        fernet_shaped = base64.urlsafe_b64encode(bytes([0x80]) + raw[1:]).decode(
            'ascii'
        )

        with pytest.raises(UndecryptableSecretError):
            decrypt_module_secret('module_a', 'enc:' + fernet_shaped)


class TestWebhookSigningSecrets:
    def test_they_belong_to_the_webhooks_module(self):
        from app.modules.webhooks._webhook_constants import decrypt_secret
        from app.modules.webhooks.webhook_service import encrypt_secret

        stored = encrypt_secret('hmac-key')

        assert decrypt_secret(stored) == 'hmac-key'
        with pytest.raises(PermissionError):
            decrypt_module_secret('some_other_module', stored)
