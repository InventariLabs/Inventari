"""The key that encrypts organization secrets is not the key that signs JWTs.

SECRET_KEY did both jobs: it signs every token *and* it is the input to the
PBKDF2 derivation behind Fernet. That coupling costs twice. Rotating the
signing key — the ordinary response to a suspected token leak, and cheap,
because it only logs everyone out — silently destroys every stored SMTP
password and API key at the same time. And one leaked value opens both.

ENCRYPTION_KEY is now its own setting. Values written under the old
derivation still read back: decryption tries the current key and then the
legacy SECRET_KEY one, and the next save rewrites them under the new key.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config import settings
from app.services import crypto_service

pytestmark = pytest.mark.unit

SECRET = 'signing-key-that-is-long-enough-for-hs256'
ENCRYPTION = 'a-separate-encryption-key-long-enough-too'


def _clear_key_cache() -> None:
    for cached in (
        crypto_service._get_fernet,
        crypto_service._previous_fernets,
        crypto_service._get_module_aead,
        crypto_service._previous_module_aeads,
    ):
        cached.cache_clear()


@pytest.fixture(autouse=True)
def _clean_key_cache() -> Iterator[None]:
    yield
    _clear_key_cache()


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    secret: str,
    encryption: str,
    previous: str = '',
) -> None:
    monkeypatch.setattr(settings, 'SECRET_KEY', secret)
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', encryption)
    monkeypatch.setattr(settings, 'PREVIOUS_ENCRYPTION_KEY', previous)
    monkeypatch.setattr(settings, 'FERNET_SALT', 'salt-that-is-long-enough-here')
    _clear_key_cache()


class TestTheTwoKeysAreIndependent:
    def test_a_secret_survives_a_round_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)

        assert (
            crypto_service.decrypt_value(crypto_service.encrypt_value('hunter2'))
            == 'hunter2'
        )

    def test_rotating_the_signing_key_leaves_the_secret_readable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: logging everyone out must not cost the SMTP password."""
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)
        stored = crypto_service.encrypt_value('hunter2')

        _configure(
            monkeypatch,
            secret='a-completely-different-signing-key!!',
            encryption=ENCRYPTION,
        )

        assert crypto_service.decrypt_value(stored) == 'hunter2'

    def test_rotating_the_encryption_key_does_not_read_the_old_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unchanged behaviour: a rotated encryption key is a hard break."""
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)
        stored = crypto_service.encrypt_value('hunter2')

        _configure(
            monkeypatch, secret=SECRET, encryption='another-encryption-key-entirely!!'
        )

        with pytest.raises(crypto_service.UndecryptableSecretError):
            crypto_service.decrypt_value(stored)

    def test_the_lenient_reader_reads_the_same_value_as_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Display paths (the settings walk) take the lenient reader: an
        unreadable secret renders as empty so the page stays loadable and
        the operator can re-enter — the strict reader's refusal is for
        callers that act on the value."""
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)
        stored = crypto_service.encrypt_value('hunter2')

        _configure(
            monkeypatch, secret=SECRET, encryption='another-encryption-key-entirely!!'
        )

        assert crypto_service.decrypt_value_lenient(stored) == ''
        # A legally empty or plain value reads the same both ways.
        assert crypto_service.decrypt_value_lenient('') == ''
        assert crypto_service.decrypt_value_lenient('old-plain-key') == 'old-plain-key'


class TestValuesWrittenBeforeTheSplit:
    def test_they_still_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _configure(monkeypatch, secret=SECRET, encryption='')
        legacy = crypto_service.encrypt_value('hunter2')

        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)

        assert crypto_service.decrypt_value(legacy) == 'hunter2'

    def test_the_next_write_uses_the_new_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)
        rewritten = crypto_service.encrypt_value('hunter2')

        # Only the new key opens it: the legacy derivation must not.
        _configure(monkeypatch, secret=SECRET, encryption='')

        with pytest.raises(crypto_service.UndecryptableSecretError):
            crypto_service.decrypt_value(rewritten)


class TestModuleSecretsWrittenBeforeTheSplit:
    def test_they_still_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting ENCRYPTION_KEY on an existing install must not cost the
        webhook signing secrets: the bound format reads SECRET_KEY too."""
        _configure(monkeypatch, secret=SECRET, encryption='')
        legacy = crypto_service.encrypt_module_secret('webhooks', 'hmac-key')

        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)

        assert crypto_service.decrypt_module_secret('webhooks', legacy) == 'hmac-key'

    def test_the_binding_still_holds_under_the_old_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(monkeypatch, secret=SECRET, encryption='')
        legacy = crypto_service.encrypt_module_secret('webhooks', 'hmac-key')

        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)

        with pytest.raises(PermissionError):
            crypto_service.decrypt_module_secret('recipes', legacy)


class TestThePreviousKey:
    def test_it_reads_what_the_rotated_key_wrote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(monkeypatch, secret=SECRET, encryption=ENCRYPTION)
        app = crypto_service.encrypt_value('hunter2')
        bound = crypto_service.encrypt_module_secret('webhooks', 'hmac-key')

        rotated = 'the-encryption-key-after-the-rotation!'
        _configure(monkeypatch, secret=SECRET, encryption=rotated, previous=ENCRYPTION)

        assert crypto_service.decrypt_value(app) == 'hunter2'
        assert crypto_service.decrypt_module_secret('webhooks', bound) == 'hmac-key'

    def test_it_is_never_written_with(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rotated = 'the-encryption-key-after-the-rotation!'
        _configure(monkeypatch, secret=SECRET, encryption=rotated, previous=ENCRYPTION)
        stored = crypto_service.encrypt_value('hunter2')

        _configure(monkeypatch, secret=SECRET, encryption=rotated)

        assert crypto_service.decrypt_value(stored) == 'hunter2'


class TestWithoutTheNewSetting:
    def test_nothing_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An install that has not set ENCRYPTION_KEY keeps working as before."""
        _configure(monkeypatch, secret=SECRET, encryption='')

        assert (
            crypto_service.decrypt_value(crypto_service.encrypt_value('hunter2'))
            == 'hunter2'
        )
