"""Unit tests for app.core.llm.secrets.

These are thin pass-through wrappers around
:mod:`app.services.crypto_service` — but the wrappers are what the rest
of ``core/llm`` (and the future ``ai_connections`` row encoder) calls.
The tests pin the contract:

- ``encrypt_connection_secret(s)`` returns a value that round-trips
  through ``decrypt_connection_secret``.
- ``mask_connection_secret('')`` returns ``''`` (NOT the mask) — empty
  means \"no key set\", which the UI should NOT present as a password
  field with ``***`` (that implies a key exists).
- ``mask_connection_secret(enc)`` returns the same string as
  :data:`app.services.crypto_service.MASKED_VALUE` for any non-empty
  input — regardless of whether the input is plain-text (legacy
  migration row) or Fernet ciphertext.
"""

import secrets

import pytest


class TestAnUnreadableKey:
    def test_decrypt_raises_runtime_error_naming_the_fix(self, monkeypatch):
        """A rotated encryption key or salt makes the stored key
        unreadable. The seam turns the typed error into the RuntimeError
        the client seams already speak — and the message says what fixes
        it, where an empty string said nothing and a remote 401 would
        have said less."""
        import app.core.llm.secrets as llm_secrets
        from app.core.llm.secrets import decrypt_connection_secret
        from app.services import crypto_service

        enc = crypto_service.encrypt_value('sk-or-v1-real')
        # llm/secrets imports decrypt_app_secret by name, so the seam's own
        # binding is the one to replace.
        monkeypatch.setattr(
            llm_secrets,
            'decrypt_app_secret',
            lambda value: (_ for _ in ()).throw(
                crypto_service.UndecryptableSecretError('rotated')
            ),
        )

        with pytest.raises(RuntimeError, match='re-enter the key'):
            decrypt_connection_secret(enc)


class TestEncryptDecryptRoundtrip:
    def test_encrypt_then_decrypt_returns_original(self):
        from app.core.llm.secrets import (
            decrypt_connection_secret,
            encrypt_connection_secret,
        )

        plaintext = 'sk-or-v1-' + secrets.token_hex(16)
        enc = encrypt_connection_secret(plaintext)
        assert enc.startswith('enc:')
        assert decrypt_connection_secret(enc) == plaintext

    def test_encrypt_idempotent(self):
        """Encrypting an already-encrypted value should be a no-op so
        that callers may safely call ``encrypt_connection_secret`` on
        values returned from the DB without double-wrapping."""
        from app.core.llm.secrets import encrypt_connection_secret

        plaintext = 'sk-or-v1-test'
        enc = encrypt_connection_secret(plaintext)
        again = encrypt_connection_secret(enc)
        assert again == enc

    def test_decrypt_legacy_plaintext_passthrough(self):
        """Same backward-compat as crypto_service.decrypt_value: rows
        saved before encryption was introduced stay readable."""
        from app.core.llm.secrets import decrypt_connection_secret

        legacy = 'old-plain-key'
        assert decrypt_connection_secret(legacy) == legacy


class TestMasking:
    """The frontend shows a password-like field whenever the mask
    appears. Critical UX rule: ``mask_connection_secret('')`` must
    return ``''`` so the password field renders as empty (not as
    ``**********``, which would imply \"I already have a key; click
    Edit to change it\")."""

    def test_mask_empty_returns_empty(self):
        from app.core.llm.secrets import mask_connection_secret

        assert mask_connection_secret('') == ''

    def test_mask_encrypted_returns_masked_value(self):
        from app.core.llm.secrets import mask_connection_secret

        # Caller may not know whether the input is encrypted or plain.
        # Both must produce the same masked output.
        from app.services.crypto_service import (
            MASKED_VALUE,
            encrypt_value,
        )

        enc = encrypt_value('sk-or-secret')
        assert mask_connection_secret(enc) == MASKED_VALUE

    def test_mask_plaintext_returns_masked_value(self):
        """Legacy rows whose key was saved BEFORE encryption was
        introduced must still mask on read."""
        from app.core.llm.secrets import mask_connection_secret
        from app.services.crypto_service import MASKED_VALUE

        assert mask_connection_secret('legacy-plain-key') == MASKED_VALUE
