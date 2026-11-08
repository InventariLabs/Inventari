"""
Module-safe settings API with per-module namespace isolation.

Settings are stored inside ``organization.settings`` (JSON field) under a
namespaced key using the pattern ``module:<module_name>``.  This prevents
collisions between different modules or with core settings.

Secret fields (declared as ``{"type": "string", "format": "secret"}`` in
the module's ``get_settings_schema()``) are encrypted on write and
masked on read by :meth:`CoreSettingsAPI.get_async` so the frontend never
sees plaintext secrets. Modules that need the real value at runtime call
:meth:`CoreSettingsAPI.get_decrypted_async` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ContractViolationError
from app.core.logging import get_logger
from app.core.module_identity import refuse_foreign_module
from app.core.settings_validator import (
    SCHEMA_VERSION_KEY,
    UNSTAMPED_SCHEMA_VERSION,
    iter_secret_paths,
)
from app.services.crypto_service import MASKED_VALUE, decrypt_module_secret
from app.services.module_settings_service import namespace

logger = get_logger(__name__)

#: Any JSON-serialisable value (string, number, bool, ``None``, list, dict).
#: ``Any`` would also fit but this alias documents the intent at the API
#: boundary and survives strict mypy checks for this module.
JSONValue = Any
JSONObject = dict[str, JSONValue]


class CoreSettingsAPI:
    """Public Core API for module settings with namespace-per-module isolation.

    Settings are stored per-module under a namespaced key::

        core_api.settings.set(db, org_id, 'my_module', 'api_key', 'secret')
        # Stored as: organization.settings['module:my_module']['api_key'] = 'secret'

    SECURITY — Namespace isolation is enforced at the API boundary. The
    caller's identity travels in a ContextVar set at the request, lifecycle,
    scheduler and event-dispatch boundaries (``app.core.module_identity``):
    a module may name its own namespace and nothing else, and a call that
    names another module is refused with ``PermissionError``. Core code
    runs with no identity bound and may speak for any module — that is the
    settings screen and the module-management endpoints. Do NOT expose
    ``module_name`` or ``key`` as user-controllable parameters in router
    endpoints; a module endpoint has no business relaying either.
    """

    def _namespace(self, module_name: str) -> str:
        return namespace(module_name)

    async def set_bulk_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module_name: str,
        values: JSONObject,
    ) -> None:
        """Async: set multiple module settings at once (shallow merge).

        The stored blob is stamped with the version of the settings schema
        it was written against, so a later shape change can tell what each
        organization actually saved.
        """
        refuse_foreign_module(module_name, api='core_api.settings.set_bulk_async')
        from app.services.module_settings_service import write_module_settings_async

        await write_module_settings_async(db, organization_id, module_name, values)

    @staticmethod
    def encrypt_secret(module_name: str, value: str) -> str:
        """Return *value* at rest, bound to *module_name*.

        For code that has to write a settings secret outside the normal
        PUT path — a one-time migration moving a key from a pre-schema
        location, for instance. Idempotent: an already-encrypted value is
        returned unchanged.

        The module name is authenticated data inside the cipher, so the
        stored text cannot be read as another module's secret and cannot
        be edited into one. It used to take only the value and call
        ``encrypt_value``, which binds nothing: its docstring said
        "modules use this instead of reaching into the crypto service"
        while producing exactly what reaching into the crypto service
        produces, and a secret written through it read back as any
        module's. The name is now a parameter because a function that
        cannot name the owner cannot bind to it.

        Core secrets that belong to the installation rather than to a
        module — the SMTP password, a provider API key — go through
        :meth:`encrypt_app_secret`, which says so.
        """
        from app.services.crypto_service import _ENC_PREFIX, encrypt_module_secret

        refuse_foreign_module(module_name, api='core_api.settings.encrypt_secret')
        # Idempotent, like the helper this replaced: callers re-save values
        # they read back, and wrapping a ciphertext twice would make it
        # unreadable. A value already bound to a *different* module passes
        # through untouched — there is no way to tell without decrypting
        # it, and decrypting it is exactly what the binding forbids.
        if not value or value.startswith(_ENC_PREFIX):
            return value
        return encrypt_module_secret(module_name, value)

    async def get_default_org_limits_async(self, db: AsyncSession) -> dict[str, Any]:
        """Async: return default AI/item/member limits for new organizations."""
        from app.services.system_settings_service import get_default_org_limits_async

        return await get_default_org_limits_async(db)

    async def get_org_limits_async(
        self, db: AsyncSession, organization_id: UUID
    ) -> dict[str, Any]:
        """Async: return effective AI limits for *organization_id*."""
        from app.services.ai_usage_service import get_org_limits_async

        return await get_org_limits_async(db, organization_id)

    async def get_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module_name: str,
        key: str | None = None,
        default: JSONValue = None,
    ) -> JSONValue:
        """Async: read a module setting. Secret fields are masked.

        ``key`` may use dotted notation to read nested values, e.g.
        ``"jina.api_key"`` returns the masked secret at that path.
        """
        refuse_foreign_module(module_name, api='core_api.settings.get_async')
        from app.services._org_reads import get_by_id_async

        org = await get_by_id_async(db, organization_id)
        if not org or not org.settings:
            return default

        module_settings: JSONObject = self._without_stamp(
            org.settings.get(self._namespace(module_name), {})
        )
        if key is None:
            return self._mask_secrets(module_settings, module_name)

        path = tuple(key.split('.')) if '.' in key else (key,)
        value = _lookup_path(module_settings, path, default)
        if path in self._secret_paths_for(module_name):
            return self._maybe_mask(value)
        return value

    async def get_decrypted_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module_name: str,
        key: str | None = None,
        default: JSONValue = None,
    ) -> JSONValue:
        """Async: the plaintext value of one secret field for *module_name*.

        ``key`` may use dotted notation for nested paths. Use this from
        module runtime code (e.g. webhooks worker, jina scraper) where the
        decrypted value is required. Never expose the result to the
        frontend.

        One field, named -- and only that. Called without a ``key`` it used
        to hand back the whole settings object exactly as stored, which for
        a secret field is the ciphertext: the name promised plaintext and
        that branch quietly did not deliver it, with nothing in the value to
        tell the caller apart from a plaintext one. It now refuses, because
        decrypting a whole namespace at once is the thing this method's own
        warning says not to do. Use :meth:`get_async` for the masked object,
        or ask for one field at a time.

        :raises ContractViolationError: when called without a ``key``.
        """
        refuse_foreign_module(module_name, api='core_api.settings.get_decrypted_async')
        if key is None:
            raise ContractViolationError(
                'get_decrypted_async needs a key: it decrypts one named '
                'secret field, never a whole namespace. Use get_async for '
                'the masked settings object.'
            )
        from app.services._org_reads import get_by_id_async

        org = await get_by_id_async(db, organization_id)
        if not org or not org.settings:
            return default

        module_settings: JSONObject = self._without_stamp(
            org.settings.get(self._namespace(module_name), {})
        )
        path = tuple(key.split('.')) if '.' in key else (key,)
        value = _lookup_path(module_settings, path, default)
        if isinstance(value, str):
            # Bound values verify the owner; the two legacy shapes written
            # before binding existed are still read, so nothing stored
            # earlier becomes unreadable the day this ships.
            return decrypt_module_secret(module_name, value)
        return value

    async def list_system_settings_async(
        self, db: AsyncSession
    ) -> list[dict[str, Any]]:
        """Return all global system settings rows (model pricing, default limits)."""
        from app.services.system_settings_service import get_all_settings_async

        return await get_all_settings_async(db)

    async def set_system_setting_async(
        self,
        db: AsyncSession,
        key: str,
        value: JSONValue,
        updated_by: UUID | None = None,
    ) -> tuple[str, JSONValue, datetime | None]:
        """Upsert a global system setting; invalidates the in-process cache.

        Returns the persisted ``(key, value, updated_at)`` triple so callers
        can shape response payloads without re-reading the row.
        """
        from app.services.system_settings_service import set_setting_async

        row = await set_setting_async(db, key, value, updated_by=updated_by)
        return row.key, row.value, row.updated_at

    async def get_schema_version_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        module_name: str,
    ) -> int:
        """Async: the settings-schema version this organization's blob carries.

        The version of the settings *shape* the blob was written against —
        not the module's own version. A blob saved before versioning existed
        reads as ``0``, so a module's per-organization migration pass knows
        it is looking at the oldest shape. A stamp that is not a usable
        positive integer reads the same way.
        """
        refuse_foreign_module(
            module_name, api='core_api.settings.get_schema_version_async'
        )
        from app.services._org_reads import get_by_id_async

        org = await get_by_id_async(db, organization_id)
        if not org or not org.settings:
            return UNSTAMPED_SCHEMA_VERSION

        module_settings: JSONObject = org.settings.get(self._namespace(module_name), {})
        return _stored_schema_version(module_settings)

    async def migrate_settings_async(
        self,
        db: AsyncSession,
        module_name: str,
        migrate: Callable[..., Any],
    ) -> int:
        """Async: rewrite every organization's settings blob for *module_name*.

        The per-organization pass a module runs when its settings shape
        changes. Every organization whose blob carries a version older than
        the schema's declared ``version`` is offered to ``migrate``::

            def migrate(organization_id, from_version, settings) -> dict | None

        ``settings`` is the blob without core's stamp; ``from_version`` is
        what the blob was written against (``0`` for a blob saved before
        versioning). The callback returns the new settings, or ``None`` to
        keep the data as it is — in-place edits of the given dict are
        honoured too. It may be async. A blob already at the declared version
        is skipped, so the pass is safe to run again.

        The migrated blob is stamped with the declared version. Secrets stay
        ciphertext: the pass sees them as stored and must round-trip them
        unchanged.

        Flushes; the caller owns the transaction. Returns the number of
        blobs rewritten.
        """
        refuse_foreign_module(
            module_name, api='core_api.settings.migrate_settings_async'
        )
        from app.core.async_utils import maybe_await
        from app.services._org_reads import list_all_async

        target = self._schema_version_for(module_name)
        ns = self._namespace(module_name)
        migrated = 0
        for org in await list_all_async(db):
            settings = org.settings or {}
            blob = settings.get(ns)
            if not isinstance(blob, dict):
                continue
            from_version = _stored_schema_version(blob)
            if from_version >= target:
                continue
            view = self._without_stamp(blob)
            rewritten = await maybe_await(migrate, org.id, from_version, view)
            if rewritten is None:
                rewritten = view
            if not isinstance(rewritten, dict):
                raise ContractViolationError(
                    'migrate must return a settings dict or None, got '
                    f'{type(rewritten).__name__}'
                )
            # A fresh outer dict on purpose: JSON columns track change by
            # object identity, and this is a write even when the data is not.
            org.settings = {
                **settings,
                ns: {**rewritten, SCHEMA_VERSION_KEY: target},
            }
            migrated += 1
        await db.flush()
        return migrated

    # ------------------------------------------------------------------
    # Secret handling — module schema declares `format: secret` leaves;
    # we mask them on read and decrypt them only via get_decrypted_async.
    # ------------------------------------------------------------------

    @staticmethod
    def _secret_paths_for(module_name: str) -> list[tuple[str, ...]]:
        try:
            from app.core.module_registry import module_registry
        except ImportError:
            return []
        instance = module_registry.get(module_name)
        if instance is None:
            return []
        try:
            schema = instance.get_settings_schema()
        except Exception as exc:  # noqa: BLE001 — a module's own code must not break the settings read
            logger.warning(
                'Failed to load settings schema for %s: %s', module_name, exc
            )
            return []
        if not schema:
            return []
        return list(iter_secret_paths(schema))

    @staticmethod
    def _schema_version_for(module_name: str) -> int:
        """The settings-schema version *module_name* declares, default 1."""
        from app.services.module_settings_service import schema_version_for

        return schema_version_for(module_name)

    @staticmethod
    def _without_stamp(module_settings: JSONObject) -> JSONObject:
        """The stored blob without core's schema-version stamp."""
        from app.services.module_settings_service import without_stamp

        return without_stamp(module_settings)

    @staticmethod
    def _maybe_mask(value: JSONValue) -> JSONValue:
        if isinstance(value, str) and value:
            return MASKED_VALUE
        return value

    def _mask_secrets(
        self, module_settings: JSONObject, module_name: str
    ) -> JSONObject:
        if not module_settings:
            return module_settings
        paths = self._secret_paths_for(module_name)
        if not paths:
            return module_settings

        result: JSONObject = {**module_settings}
        for path in paths:
            result = _mask_leaf(result, path)
        return result


def _stored_schema_version(module_settings: dict[str, Any]) -> int:
    """The stamp on a stored blob — 0 when it has none or an unreadable one.

    Version 0 means "written before versioning existed", which is what a
    per-organization migration pass needs to see for a blob nobody stamped.
    """
    raw = module_settings.get(SCHEMA_VERSION_KEY)
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return UNSTAMPED_SCHEMA_VERSION


def _mask_leaf(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    if not path:
        return data
    head, *rest = path
    if not isinstance(data, dict) or head not in data:
        return data
    new_data = {**data}
    if not rest:
        new_data[head] = (
            MASKED_VALUE if isinstance(data[head], str) and data[head] else data[head]
        )
    else:
        new_data[head] = _mask_leaf(data[head], tuple(rest))
    return new_data


def _lookup_path(data: Any, path: tuple[str, ...], default: Any = None) -> Any:
    cur = data
    for segment in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(segment)
        if cur is None:
            return default
    return cur


__all__ = ['CoreSettingsAPI', 'JSONObject', 'JSONValue']
