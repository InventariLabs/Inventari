"""Module-safe wrapper around core crypto utilities.

Modules MUST import from here (app.core.public_api), never directly from
app.services.crypto_service.  This keeps the service boundary clear and
lets the implementation evolve without touching every consumer.

``encrypt_for_module`` / ``decrypt_for_module`` were added
with per-module isolation. The unbound ``encrypt`` / ``decrypt`` that
preceded them are gone — they offered no isolation, so module A could
read module B's secrets — and they left before this repository became
public, while the only callers were in this tree.

The owner module is authenticated data INSIDE the cipher (AES-256-GCM
AAD), so a secret stored for one module is unreadable as another's, and
editing the stored text is a refusal rather than a read. Values written
by the retired suffix format — and values written by the removed bare
``encrypt`` — are read without verification, because they were app-wide
by design; re-saving one binds it. That read path stays: the method is
gone, the ciphertext it produced is still in the database.
"""

from app.core.module_identity import refuse_foreign_module
from app.services.crypto_service import MASKED_VALUE
from app.services.crypto_service import decrypt_module_secret as _decrypt_bound
from app.services.crypto_service import encrypt_module_secret as _encrypt_bound


class CoreSecretsAPI:
    """Basic encryption helpers for module use."""

    #: Sentinel returned to callers instead of the raw secret.
    MASKED = MASKED_VALUE

    def encrypt_for_module(self, module_name: str, value: str) -> str:
        """Encrypt *value* cryptographically bound to *module_name*.

        The name is authenticated data inside the cipher, so a value
        stored for one module cannot be read as another module's, and
        the stored text cannot be edited into a different module's
        secret. Returns ``enc:mod1:<ciphertext>``.

        Raises ``PermissionError`` when the caller is a module naming a
        different module's namespace (``app.core.module_identity``).
        """
        refuse_foreign_module(module_name, api='core_api.secrets.encrypt_for_module')
        return _encrypt_bound(module_name, value)

    def decrypt_for_module(self, module_name: str, value: str) -> str:
        """Decrypt *value* written by :meth:`encrypt_for_module`.

        Raises ``PermissionError`` when the value is not bound to
        *module_name* — another module's secret, stored text that was
        edited along the way, or stored text whose ``enc:mod1:`` marker
        was renamed or stripped. The last case carries a sealed body but
        no readable marker; refusing it beats returning an empty string
        and logging a key-rotation hint nobody needs.

        Raises :class:`~app.services.crypto_service.UndecryptableSecretError`
        when the body is well-shaped but no known key opens it (a rotation
        since it was saved). Same contract: "unreadable" must not arrive
        disguised as an empty secret.

        Two legacy shapes are decrypted WITHOUT verification and stay
        readable for data written before binding existed. They were
        app-wide by design, not per-module:

        - ``enc:<cipher>:<name>`` — the retired suffix format; the name
          was a label beside the cipher, never proof of anything.
          Re-save the value through :meth:`encrypt_for_module` to bind
          it.
        - ``enc:<cipher>`` or plaintext — from the deprecated
          :meth:`encrypt`; isolated by nothing.

        Raises ``PermissionError`` when the caller is a module naming a
        different module's namespace (``app.core.module_identity``).
        """
        refuse_foreign_module(module_name, api='core_api.secrets.decrypt_for_module')
        return _decrypt_bound(module_name, value)
