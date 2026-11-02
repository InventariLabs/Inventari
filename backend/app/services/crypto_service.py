"""
Encryption helpers for sensitive values stored in organization settings.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) with a key
derived from ENCRYPTION_KEY (SECRET_KEY when it is empty) via
PBKDF2-HMAC-SHA256 (600 000 iterations) so brute-force of the encryption key
is computationally infeasible. Values are read under the previous keys too
(``_previous_materials``) and rewritten under the current one by
``manage.py secrets reencrypt``.

Sensitive paths encrypted/decrypted automatically:
  - settings.llm.api_key
  - settings.smtp.password
  - settings.modules.recipes.jina.api_key  (added in Jina security fix)
"""

import base64
import binascii
import hashlib
import os
from collections.abc import Callable
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.core.exceptions import ContractViolationError
from app.core.logging import get_logger
from app.core.settings_diff import CIPHERTEXT_PREFIX

logger = get_logger(__name__)


class UndecryptableSecretError(ValueError):
    """Raised when stored ciphertext cannot be opened by any known key.

    "Cannot read this secret" is a different answer from "the secret is
    empty", and only the type system keeps the two apart: every caller
    that would otherwise have compared the result against ``''`` now has
    to decide what an unreadable secret means for it — refuse delivery,
    surface a re-enter hint, or knowingly degrade on a display path.

    The message is for the operator reading a log or the ``secrets`` CLI,
    never a sentence for a reader: ``reader_facing = False`` makes an
    uncaught one answer with the generic translated sentence, and the
    callers that tell a reader to re-enter the secret say so with a
    catalogue key of their own.
    """

    reader_facing = False


class ModuleSecretBindingError(PermissionError):
    """A module asked for a secret that is not bound to it, or whose binding was edited.

    A ``PermissionError`` so every caller that already refuses on one keeps
    doing so. Like :class:`UndecryptableSecretError` the message is for the
    log and the ``secrets`` CLI, not for a reader (``reader_facing = False``).
    """

    reader_facing = False


# Sentinel stored in DB instead of plaintext. The journal recognises a
# ciphertext by the same prefix and cannot import this module, so the one
# spelling lives in the core and is read from there.
_ENC_PREFIX = CIPHERTEXT_PREFIX

# Module-bound secrets: the owner module is authenticated data inside the
# cipher (AES-256-GCM), not a readable tag beside it.
_MODULE_AEAD_MARK = 'mod1:'
_MODULE_AEAD_PREFIX = _ENC_PREFIX + _MODULE_AEAD_MARK
_MODULE_AEAD_NONCE_BYTES = 12
_MODULE_AAD = b'inventari/module-secret/v1'
_MODULE_KDF_INFO = b'inventari/module-secret-binding/v1'

# Value returned to the frontend when a secret is set — never the real value
MASKED_VALUE = '**********'
# Dot-paths of sensitive leaf values in organization settings. Tuples may be
# of any depth >= 2 — the implementation walks nested dicts recursively.
# Adding the jina path closes a security gap: keys were read decrypted by
# services but never auto-encrypted on save nor masked on read.
SENSITIVE_PATHS: list[tuple[str, ...]] = [
    ('llm', 'api_key'),
    ('smtp', 'password'),
    ('modules', 'recipes', 'jina', 'api_key'),
]


_KDF_ITERATIONS = 600_000


def _read_leaf(data: dict, path: tuple[str, ...]) -> str | None:
    """Return the value at the nested path, or None if any segment is missing
    or non-dict along the way. Empty string is returned as-is so that callers
    can distinguish "cleared" from "absent" when needed."""
    cur: dict | None = data
    for segment in path[:-1]:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)  # type: ignore[assignment]
        if cur is None:
            return None
    if not isinstance(cur, dict):
        return None
    return cur.get(path[-1])


def _set_leaf(data: dict, path: tuple[str, ...], value: str) -> dict:
    """Return a SHALLOW copy of *data* with the nested leaf at *path* set to
    *value*. Original dict and untouched siblings are not mutated.

    The base case (single-segment path) returns a fresh copy with the leaf
    set; multi-segment paths recurse into a freshly-copied branch dict and
    replace it at its parent key.
    """
    if len(path) == 1:
        new_data = {**data}
        new_data[path[0]] = value
        return new_data

    head = path[0]
    branch = data.get(head)
    new_branch: dict = {**branch} if isinstance(branch, dict) else {}
    new_branch = _set_leaf(new_branch, path[1:], value)
    new_data = {**data}
    new_data[head] = new_branch
    return new_data


def _fernet_from(material: str) -> Fernet:
    """Derive a Fernet instance from *material* via PBKDF2.

    The salt is ``settings.FERNET_SALT`` (per-deployment) — never a
    hardcoded constant shared across deployments.
    """
    key_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        material.encode(),
        settings.FERNET_SALT.encode('utf-8'),
        _KDF_ITERATIONS,
    )
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def _current_material() -> str:
    """``ENCRYPTION_KEY`` when the deployment sets one, ``SECRET_KEY`` otherwise."""
    return settings.ENCRYPTION_KEY or settings.SECRET_KEY


def _previous_materials() -> tuple[str, ...]:
    """Keys a stored value may still be sealed with, tried after the current one.

    ``PREVIOUS_ENCRYPTION_KEY`` is the key an operator is rotating away from;
    it keeps every secret readable until ``manage.py secrets reencrypt`` has
    rewritten them all. ``SECRET_KEY`` covers values written before
    ``ENCRYPTION_KEY`` existed — every install that never set it. The current
    key is never among them.
    """
    current = _current_material()
    found: list[str] = []
    for material in (settings.PREVIOUS_ENCRYPTION_KEY, settings.SECRET_KEY):
        if material and material != current and material not in found:
            found.append(material)
    return tuple(found)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """The key everything is written with.

    ``ENCRYPTION_KEY`` when the deployment sets one, ``SECRET_KEY`` otherwise.
    The fallback is what keeps an install that has not set the new value
    working; the setting exists because one secret doing both jobs costs
    twice. Rotating the signing key is the ordinary answer to a suspected
    token leak — cheap, because it only logs everyone out — and it silently
    destroyed every stored SMTP password and API key at the same time. One
    leaked value also opened both.

    Cached: PBKDF2 at 600 000 iterations is deliberately slow, and this is on
    the read path of the settings page.
    """
    return _fernet_from(_current_material())


@lru_cache(maxsize=1)
def _previous_fernets() -> tuple[Fernet, ...]:
    """The Fernet keys of :func:`_previous_materials`, for reading only."""
    return tuple(_fernet_from(material) for material in _previous_materials())


def encrypt_value(value: str) -> str:
    """Encrypt a plain-text secret. Returns 'enc:<ciphertext>'.
    Idempotent: already-encrypted values are returned unchanged.
    """
    if not value or value.startswith(_ENC_PREFIX):
        return value
    return _ENC_PREFIX + _get_fernet().encrypt(value.encode()).decode()


def encrypt_app_secret(value: str) -> str:
    """Encrypt a secret that belongs to the installation, not to a module.

    The SMTP password, a provider API key the core LLM client reads: things
    whose reader is core code, where there is no module to bind to. Nothing
    is bound and that is correct here — the name exists so the choice is
    visible at the call site instead of living in a docstring. A module's
    secret goes through ``encrypt_module_secret`` and the architecture lint
    refuses a module that reaches for this one.
    """
    return encrypt_value(value)


def decrypt_app_secret(value: str) -> str:
    """Read a value written by :func:`encrypt_app_secret`.

    Strict: raises :class:`UndecryptableSecretError` when the stored value
    cannot be opened (a key or salt rotation since it was saved). Callers
    act on this value — send, sign, authenticate — and an action on an
    empty string is an action on a secret that was never there.
    """
    return decrypt_value(value)


def decrypt_value(value: str) -> str:
    """Decrypt an encrypted secret, or raise :class:`UndecryptableSecretError`.

    Plain-text values pass through unchanged (backward compatibility —
    values saved before encryption was introduced), and so does an empty
    string: "never set" is a legal state and stays one.

    An unreadable ciphertext — a FERNET_SALT or encryption-key rotation
    since the value was saved — raises instead of returning
    something a caller could mistake for a legally empty secret. Callers
    decide what unreadable means for them: refuse, surface a re-enter
    hint, or knowingly degrade via :func:`decrypt_value_lenient` on a
    display path. The undecryptable ciphertext is left untouched in the
    DB; it will be overwritten on the next save.
    """
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        return (
            value  # legacy plain-text — still valid, will be re-encrypted on next save
        )
    ciphertext = value[len(_ENC_PREFIX) :].encode()
    # Then the keys it may have been written under before: the one being
    # rotated away from, and SECRET_KEY from before ENCRYPTION_KEY existed.
    # The next save, or `manage.py secrets reencrypt`, rewrites it under the
    # current key.
    for fernet in (_get_fernet(), *_previous_fernets()):
        try:
            return fernet.decrypt(ciphertext).decode()
        except InvalidToken:
            continue

    logger.warning(
        'Failed to decrypt a settings secret — FERNET_SALT or the encryption '
        'key has changed since this value was saved (C4 hard break). '
        'Re-enter the secret in the settings UI.'
    )
    raise UndecryptableSecretError(
        'the stored value cannot be decrypted with any known key '
        '(the encryption key or salt has rotated since it was saved) — '
        're-enter the secret'
    )


def decrypt_value_lenient(value: str) -> str:
    """:func:`decrypt_value` for display paths: an unreadable secret reads
    as empty instead of raising.

    Only for callers whose output is a *rendering* of the stored state —
    the settings walk below, a mask — where the page must stay loadable so
    the operator can re-enter the secret. Anything that acts on the value
    (sends it, signs with it, authenticates with it) belongs on the strict
    function, because an action on an empty string is an action taken on
    a secret that was never there.
    """
    try:
        return decrypt_value(value)
    except UndecryptableSecretError:
        return ''


def _module_aad(module_name: str) -> bytes:
    """The bytes the cipher must authenticate: a domain marker plus the
    owner's name. A value sealed for one module fails to open as another
    module's, and edited stored text fails to open at all."""
    return _MODULE_AAD + b'\x00' + module_name.encode('utf-8')


def _module_aead_from(material: str) -> AESGCM:
    """Derive the module-secret AEAD key from *material*.

    Same key material and KDF cost as the Fernet derivation, but a
    domain-separated salt: two derivations of one secret must never meet
    in two algorithms.
    """
    salt = settings.FERNET_SALT.encode('utf-8') + _MODULE_KDF_INFO
    key = hashlib.pbkdf2_hmac('sha256', material.encode('utf-8'), salt, _KDF_ITERATIONS)
    return AESGCM(key)


@lru_cache(maxsize=1)
def _get_module_aead() -> AESGCM:
    """The AEAD key module secrets are written with.

    Cached for the same reason ``_get_fernet`` is — PBKDF2 at 600 000
    iterations is a read-path cost on purpose only once.
    """
    return _module_aead_from(_current_material())


@lru_cache(maxsize=1)
def _previous_module_aeads() -> tuple[AESGCM, ...]:
    """The AEAD keys of :func:`_previous_materials`, for reading only."""
    return tuple(_module_aead_from(material) for material in _previous_materials())


def _open_bound(module_name: str, body: str, keys: tuple[AESGCM, ...]) -> str | None:
    """The plaintext of a bound body under the first of *keys* that opens
    it for *module_name*, or ``None`` when none does."""
    try:
        blob = base64.b64decode(body, altchars=b'-_', validate=True)
    except (binascii.Error, ValueError):
        return None
    for key in keys:
        try:
            plain = key.decrypt(
                blob[:_MODULE_AEAD_NONCE_BYTES],
                blob[_MODULE_AEAD_NONCE_BYTES:],
                _module_aad(module_name),
            )
        except (InvalidTag, ValueError):
            continue
        return plain.decode('utf-8')
    return None


def encrypt_module_secret(module_name: str, value: str) -> str:
    """Encrypt *value* cryptographically bound to *module_name*.

    Returns ``enc:mod1:<nonce+ciphertext>``, AES-256-GCM with the module
    name as associated data. ``decrypt_module_secret`` under any other
    name — or after any edit of the stored text — fails instead of
    yielding the plaintext.
    """
    if ':' in module_name:
        raise ContractViolationError('module name must not contain a colon')
    nonce = os.urandom(_MODULE_AEAD_NONCE_BYTES)
    sealed = _get_module_aead().encrypt(
        nonce, value.encode('utf-8'), _module_aad(module_name)
    )
    return _MODULE_AEAD_PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode(
        'ascii'
    )


def _looks_like_fernet_token(segment: str) -> bool:
    """Structural, not cryptographic: a Fernet token is urlsafe base64 that
    decodes to a payload whose first byte is the format version (0x80) and
    whose body is long enough to carry the timestamp, IV and HMAC of an
    empty message. A key rotation breaks decryption but never the shape,
    so this stays true for legacy values nobody can read anymore — which
    is what keeps the refusal below from swallowing them.
    """
    if len(segment) < 76:  # an empty-plaintext token encodes to 76 chars
        return False
    try:
        raw = base64.b64decode(segment, altchars=b'-_', validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) >= 57 and raw[0] == 0x80


def _looks_like_sealed_blob(segment: str) -> bool:
    """True for text shaped like a module-bound body: urlsafe base64 long
    enough to carry a nonce plus a ciphertext and its tag (28 bytes of a
    sealed empty string encode to 38 chars). Its first byte is the nonce,
    random by construction — and random means it is the Fernet version byte
    (0x80) about once in 256 bodies, which is the chance
    ``_carries_an_edited_marker`` deals with: a stripped marker on such a
    body reads through the legacy branch instead of being refused (measured:
    12 of 3000 generated bodies, 0.40%)."""
    if len(segment) < 38:
        return False
    try:
        base64.b64decode(segment, altchars=b'-_', validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


def _carries_an_edited_marker(value: str) -> bool:
    """True for a value shaped like a bound secret whose ``enc:mod1:``
    marker was renamed or stripped: a sealed body is still there, but no
    segment in front of it is the Fernet token both legacy formats put
    there. Very long bound values (29 bytes of plaintext or more) can in
    rare cases decode with a Fernet-looking first byte and degrade to the
    old empty read — a wrong silence, not a wrong refusal."""
    segments = value[len(_ENC_PREFIX) :].split(':')
    return _looks_like_sealed_blob(segments[-1]) and not _looks_like_fernet_token(
        segments[0]
    )


def decrypt_module_secret(module_name: str, value: str) -> str:
    """Read a value written by :func:`encrypt_module_secret`.

    Raises ``PermissionError`` when the value is not bound to
    *module_name* — another module's secret, or stored text edited on
    its way through a table row. The error is one sentence for every
    failure, so a wrong name and a tampered body are not distinguishable
    from the outside.

    A value that still carries a sealed body but whose ``enc:mod1:``
    marker was renamed or stripped is refused too, by shape: reading it
    as legacy used to return an empty string and log a key-rotation
    warning — a diagnosis pointing away from the edit — and let a
    delivery sign with an empty key.

    Two shapes written before binding are read without verification,
    because that is what they are — app-wide values, isolated by
    nothing:

    - ``enc:<cipher>:<name>`` — the retired suffix format; the name sat
      outside the cipher and never authenticated anything. Re-save the
      value through :func:`encrypt_module_secret` to bind it.
    - ``enc:<cipher>`` or plaintext — from the deprecated
      :func:`encrypt_value` path.
    """
    if value.startswith(_MODULE_AEAD_PREFIX):
        plain = _open_bound(
            module_name,
            value[len(_MODULE_AEAD_PREFIX) :],
            (_get_module_aead(), *_previous_module_aeads()),
        )
        if plain is None:
            raise ModuleSecretBindingError(
                f'Module {module_name!r} cannot decrypt a secret not bound to it'
            )
        return plain

    if value.startswith(_ENC_PREFIX) and _carries_an_edited_marker(value):
        raise ModuleSecretBindingError(
            f'Module {module_name!r} cannot read a secret whose binding '
            'marker was edited: the stored text carries a sealed body but '
            'no readable marker. Re-enter and save the value to bind it '
            'again.'
        )

    if value.startswith(_ENC_PREFIX) and value.count(':') >= 2:
        cipher, _tag = value.rsplit(':', 1)
        return decrypt_value(cipher)

    return decrypt_value(value)


def reencrypt_app_secret(value: str) -> str | None:
    """*value* sealed again under the current key, for a key rotation.

    ``None`` when there is nothing to rewrite: empty, plain text, or already
    under the current key. Raises :class:`UndecryptableSecretError` when no
    known key opens it — the caller reports it and leaves it stored as it is.
    """
    if not value or not value.startswith(_ENC_PREFIX):
        return None
    try:
        _get_fernet().decrypt(value[len(_ENC_PREFIX) :].encode())
        return None
    except InvalidToken:
        pass
    plain = decrypt_value(value)
    return _ENC_PREFIX + _get_fernet().encrypt(plain.encode()).decode()


def reencrypt_module_secret(module_name: str, value: str) -> str | None:
    """*value* sealed again for *module_name* under the current key.

    ``None`` when there is nothing to rewrite: empty, plain text, or already
    readable under the current key. Anything else is read the way
    :func:`decrypt_module_secret` reads it and written the way
    :func:`encrypt_module_secret` writes — so a value in a shape from before
    binding comes back bound. Raises what the reader raises when it cannot
    open the value (``PermissionError``, :class:`UndecryptableSecretError`).
    """
    if not value or not value.startswith(_ENC_PREFIX):
        return None
    if value.startswith(_MODULE_AEAD_PREFIX):
        body = value[len(_MODULE_AEAD_PREFIX) :]
        if _open_bound(module_name, body, (_get_module_aead(),)) is not None:
            return None
    elif not _carries_an_edited_marker(value):
        cipher = value.rsplit(':', 1)[0] if value.count(':') >= 2 else value
        try:
            _get_fernet().decrypt(cipher[len(_ENC_PREFIX) :].encode())
            return None
        except InvalidToken:
            pass
    return encrypt_module_secret(module_name, decrypt_module_secret(module_name, value))


def _transform_sensitive(
    org_settings: dict,
    transformer: Callable[[str], str],
) -> dict:
    """Apply *transformer* to every sensitive leaf value in org_settings.

    Walks every path in ``SENSITIVE_PATHS`` regardless of depth, so tuples
    like ``('modules', 'recipes', 'jina', 'api_key')`` are supported
    alongside legacy 2-tuples. Returns a shallow copy where each touched
    branch is itself a new dict — the original is never mutated.
    """
    result: dict = {**org_settings}
    for path in SENSITIVE_PATHS:
        leaf = _read_leaf(result, path)
        if leaf:
            result = _set_leaf(result, path, transformer(leaf))
    return result


def decrypt_settings(org_settings: dict) -> dict:
    """Return a copy of org_settings with sensitive leaf values decrypted.

    Use this only for internal service calls (Vision, SMTP) — never return
    the result of this function to the frontend.

    Lenient on purpose, for RENDERING and read-only walks: an
    undecryptable leaf reads as empty instead of taking the whole page
    down. A leaf a caller ACTS on (the SMTP password) is not answered by
    this walk — that field is re-read strictly at its acting caller, which
    is where the rotation warning gets a name and a fix.
    """
    return _transform_sensitive(org_settings, decrypt_value_lenient)


def mask_settings(org_settings: dict) -> dict:
    """Return a copy of org_settings safe for API responses.

    Sensitive values that are set are replaced with MASKED_VALUE so the
    frontend knows a secret exists without ever seeing it.
    """
    return _transform_sensitive(org_settings, lambda v: MASKED_VALUE if v else v)


def merge_incoming_settings(
    incoming: dict,
    existing_encrypted: dict | None,
) -> dict:
    """Merge incoming settings from a PUT request with the existing encrypted
    settings in the database.

    Rules (applied per path in ``SENSITIVE_PATHS``):
    - If a sensitive field arrives as ``MASKED_VALUE``, keep the existing
      encrypted value (the user did not change it).
    - If a sensitive field arrives as empty string / None / path missing,
      clear it.
    - If a sensitive field arrives as a new value, encrypt it.
    - All non-sensitive fields are taken from incoming unchanged.

    Supports both 2-tuple legacy paths (e.g. ``('llm', 'api_key')``) and
    deeper paths (e.g. ``('modules', 'recipes', 'jina', 'api_key')``).
    """
    existing = existing_encrypted or {}
    result: dict = {**incoming}

    for path in SENSITIVE_PATHS:
        incoming_val = _read_leaf(incoming, path)

        if incoming_val is None or incoming_val == '':
            continue

        if incoming_val == MASKED_VALUE:
            # User did not touch this field — restore encrypted value from DB
            existing_val = _read_leaf(existing, path) or ''
            result = _set_leaf(result, path, existing_val)
        else:
            # New value provided — encrypt it
            result = _set_leaf(result, path, encrypt_value(incoming_val))

    return result
