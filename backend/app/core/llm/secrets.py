"""Thin encrypt / decrypt / mask helpers for ``AiConnection.api_key_enc``.

The :class:`app.models.ai_connection.AiConnection` model stores the
provider API key as a single varchar column, NOT as part of the
JSON-typed ``Organization.settings`` blob. That means the existing
``crypto_service.SENSITIVE_PATHS`` auto-walk does not handle it — we
need explicit calls every time we touch the field. The functions in
this module are the only place that does so, so they are the single
seam to audit if the encryption scheme ever changes.

All three helpers are pure pass-throughs to
:mod:`app.services.crypto_service` — the value here is the abstraction
boundary, not new logic. Callers (the ``ai_connections`` row encoder,
the ``registry`` resolver) import from
``app.core.llm.secrets``, never from ``app.services.crypto_service``,
so the dependency direction is fixed: feature → core.llm → crypto_service.
"""

from app.services.crypto_service import (
    MASKED_VALUE,
    UndecryptableSecretError,
    decrypt_app_secret,
    encrypt_app_secret,
)

__all__ = [
    'encrypt_connection_secret',
    'decrypt_connection_secret',
    'mask_connection_secret',
]


def encrypt_connection_secret(api_key: str) -> str:
    """Encrypt a provider API key for at-rest storage.

    A provider key is the installation's credential, not a module's —
    the core LLM client reads it — so it is encrypted app-wide, by the
    function whose name says so. Idempotent: encrypting an already
    encrypted value returns it unchanged, so a caller may re-apply
    encryption to a value read back from the DB.
    """
    return encrypt_app_secret(api_key)


def decrypt_connection_secret(enc: str) -> str:
    """Decrypt a stored provider API key.

    Legacy plaintext rows (saved before encryption was introduced) pass
    through unchanged so the data migration is non-blocking. An
    undecryptable ciphertext (a key or salt rotation since the row was
    written) raises RuntimeError naming the fix — the client seams above
    already speak RuntimeError for "cannot call with this key", and a
    remote 401 would say less than this does.
    """
    try:
        return decrypt_app_secret(enc)
    except UndecryptableSecretError as exc:
        raise RuntimeError(
            'the stored API key cannot be decrypted — the encryption key '
            'or salt has rotated since it was saved; re-enter the key in '
            'the AI connection form'
        ) from exc


def mask_connection_secret(enc: str) -> str:
    """Return the value safe to send to the frontend.

    - Empty / unset key → empty string. This makes the password field
      render empty (NOT ``**********``); ``**********`` implies \"I have
      a key, click Edit to change it\".
    - Any non-empty value (plaintext or Fernet ciphertext) → MASKED_VALUE.
      The frontend treats both the same way: render the password box with
      placeholder dots and let the user overwrite with a new key on save.
    """
    if not enc:
        return ''
    return MASKED_VALUE
