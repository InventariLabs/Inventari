from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import ServiceRejectionError, catalogue_refusal
from app.core.logging import get_logger
from app.core.module_registry import module_registry
from app.core.module_tracking import load_module_tracking
from app.core.settings_diff import MASKED_VALUE, changed_settings_snapshot
from app.core.settings_validator import (
    SCHEMA_VERSION_KEY,
    iter_secret_paths,
    settings_schema_version,
    validate_payload_against_schema,
)
from app.core.version import check_min_version, get_platform_version
from app.services.audit_service import log_action_async
from app.services.crypto_service import encrypt_module_secret
from app.services.module_lifecycle_service import (
    disable_modules_async,
    enable_modules_async,
)

if TYPE_CHECKING:
    from app.models.organization import Organization

logger = get_logger(__name__)


class ModuleService:
    @staticmethod
    async def toggle_module(
        db: AsyncSession,
        organization: Organization,
        module_name: str,
        enabled: bool,
        user: UserContextDTO,
    ) -> list[str]:
        """Enable/disable a module for the organization.

               Hook execution is delegated to the shared lifecycle executor
        — one code path, ``ModuleLifecycleError`` on hook
               failure (the caller rolls back). This method owns the
               ``enabled_modules`` list update, the commit, and the
               module.enabled/disabled event.
        """
        # Serialize concurrent toggles on the organization row: a plain
        # read-modify-write loses updates when two toggles interleave (each
        # commits its own stale snapshot of enabled_modules), which surfaced
        # as modules randomly dropping out mid-run. Re-read the row under a
        # lock so the list edit below starts from the latest committed state.
        # The deferred onboarding columns are undeferred up front — reading
        # them cold would fire a lazy SELECT outside the greenlet.
        from sqlalchemy import select
        from sqlalchemy.orm import undefer

        from app.models.organization import Organization

        locked_org = await db.scalar(
            select(Organization)
            .options(
                undefer(Organization.onboarding_completed),
                undefer(Organization.pre_onboarding_manual_modules),
            )
            .where(Organization.id == organization.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_org is None:
            raise catalogue_refusal('organization_not_found')
        organization = locked_org

        module_instance = module_registry.get(module_name)
        current_modules = list(organization.enabled_modules or [])
        was_enabled = module_name in current_modules

        if enabled:
            if module_name not in current_modules:
                _refuse_if_platform_too_old(module_name)
                current_modules.append(module_name)
                if module_instance:
                    await enable_modules_async(
                        [module_instance], organization.id, db=db, user=user
                    )
        else:
            if module_name in current_modules:
                current_modules.remove(module_name)
                if module_instance:
                    await disable_modules_async(
                        [module_instance], organization.id, db=db, user=user
                    )

        organization.enabled_modules = current_modules
        # While onboarding still stands open, the toggle is the admin's
        # explicit answer about how this organization works — a fresh org
        # holds only the always-on set, so anything written here was chosen
        # by hand. Recorded, because completing onboarding replaces
        # ``enabled_modules`` with the chosen profile's set: without the
        # record, a module the profile does not offer was dropped without
        # its disable hook and without a word. A toggle off
        # takes the name back out — a reversed choice is an answer too.
        if not organization.onboarding_completed:
            manual = list(organization.pre_onboarding_manual_modules or [])
            if enabled:
                if module_name not in manual:
                    manual.append(module_name)
            elif module_name in manual:
                manual.remove(module_name)
            organization.pre_onboarding_manual_modules = manual
        # Switching a module changes what the whole organization can do. A
        # toggle that changed nothing is not an act — only a real switch is
        # recorded, and its entry rides the caller's commit.
        if was_enabled != enabled:
            await log_action_async(
                db,
                organization_id=organization.id,
                user_id=user.id,
                action=AuditAction.UPDATE,
                target_type=AuditTargetType.MODULE,
                target_id=organization.id,
                snapshot={
                    'name': module_name,
                    'before': {'enabled': was_enabled},
                    'after': {'enabled': enabled},
                },
            )
        event = SystemEvent.MODULE_ENABLED if enabled else SystemEvent.MODULE_DISABLED
        await event_bus.emit_transactional(
            db,
            event,
            TenantEventPayload.model_validate(
                {'organization_id': str(organization.id), 'module_name': module_name}
            ),
        )
        await db.flush()
        return current_modules

    @staticmethod
    async def update_module_settings_async(
        db: AsyncSession, organization_id: UUID, module_name: str, settings: dict
    ) -> dict[str, dict[str, Any]] | None:
        """Validate and store one module's settings, reporting what moved.

        The write is a partial update: the body merges over the saved
        settings at the top level, so a key the client omits keeps its
        saved value — a full-replacement write is what the
        caller composes by sending every key.

        The return value carries before/after for the top-level keys that
        changed — ``None`` when the write changes nothing — with secret
        leaves masked. The caller, which knows the actor, turns it into the
        journal entry; a settings write that silently decided who may close
        their own approval used to leave no trace at all.
        """
        from app.services._org_reads import get_by_id_async

        org = await get_by_id_async(db, organization_id)
        if not org:
            raise ServiceRejectionError('organization_not_found')

        schema = ModuleService._get_module_settings_schema(module_name)
        cleaned = ModuleService._validate_and_clean(settings, schema)
        encrypted = ModuleService._encrypt_secret_fields(cleaned, schema, module_name)

        import copy

        namespace = f'module:{module_name}'
        org_settings = copy.deepcopy(org.settings or {})
        raw_before = copy.deepcopy(org_settings.get(namespace, {}))
        # Partial update: the body merges over the saved settings
        # at the top level, so a key the client omits keeps its saved value —
        # a secret among them keeps its stored ciphertext and is not
        # re-encrypted. Schema defaults land only on keys that were neither
        # sent nor saved before, keeping storage complete for the readers
        # that read the raw namespace; a default is never a secret, so the
        # fill happens after encryption on purpose.
        merged = dict(raw_before)
        merged.update(encrypted)
        properties = (schema or {}).get('properties') or {}
        for key, prop in properties.items():
            if key not in merged and isinstance(prop, dict) and 'default' in prop:
                merged[key] = prop['default']
        if namespace not in org_settings:
            org_settings[namespace] = {}
        # The stamp is core's metadata about the blob: written last so it
        # records the shape this write produced, whatever came in. The
        # partial merge above may have carried an older stamp over from the
        # saved blob, and a payload echoing one is ignored by the validator.
        merged[SCHEMA_VERSION_KEY] = settings_schema_version(schema)
        org_settings[namespace] = merged
        org.settings = org_settings
        await db.flush()

        return ModuleService.settings_change_snapshot(
            module_name, schema, raw_before, org_settings[namespace]
        )

    @staticmethod
    def settings_change_snapshot(
        module_name: str,
        schema: dict[str, Any] | None,
        raw_before: dict[str, Any],
        raw_after: dict[str, Any],
    ) -> dict[str, dict[str, Any]] | None:
        """Before/after for the top-level keys that moved, secrets masked.

        Public because a namespace does not have to be written through this
        service to earn a journal entry: a profile's ``module_config`` is
        merged in by ``profile_module_config_service`` and reports what moved
        in the same shape.

        Absence reads as the schema default on both sides: writing False
        over an unset False-default changed nothing, and the journal records
        changes, not keystrokes. Change detection reads the stored values,
        so for a secret it sees the ciphertext — a resave names the key even
        though the snapshot shows only the mask, because encryption does
        not repeat and missing the touch of a secret is the expensive
        direction to be wrong in.
        """
        secret_paths = set(iter_secret_paths(schema)) if schema else set()
        defaults = {
            name: prop['default']
            for name, prop in ((schema or {}).get('properties') or {}).items()
            if isinstance(prop, dict) and 'default' in prop
        }

        def _effective(raw: dict[str, Any], key: str) -> Any:
            if key in raw:
                return raw[key]
            return defaults.get(key)

        keys = sorted(set(raw_before) | set(raw_after))
        effective_before = {key: _effective(raw_before, key) for key in keys}
        effective_after = {key: raw_after.get(key) for key in keys}
        # The schema-version stamp is core's metadata, not a reader's edit:
        # a journal entry names the keys that moved, and a write that only
        # re-stamped the blob moved none.
        effective_before.pop(SCHEMA_VERSION_KEY, None)
        effective_after.pop(SCHEMA_VERSION_KEY, None)
        return changed_settings_snapshot(
            effective_before, effective_after, secret_paths
        )

    @staticmethod
    def _get_module_settings_schema(module_name: str) -> dict[str, Any] | None:
        instance = module_registry.get(module_name)
        if instance is None:
            return None
        try:
            return instance.get_settings_schema()
        except Exception:  # a module's own code; logged, the schema reads as absent
            logger.exception('Module %s raised in get_settings_schema()', module_name)
            return None

    @staticmethod
    def _validate_and_clean(
        payload: dict[str, Any], schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Validate the payload as the client sent it — a partial body stays
        partial. Schema defaults are NOT filled here: the write merges over
        the saved settings, and filling would overwrite the saved
        values of keys the client omitted."""
        if not schema:
            return dict(payload)

        return validate_payload_against_schema(payload, schema)

    @staticmethod
    def _encrypt_secret_fields(
        cleaned: dict[str, Any], schema: dict[str, Any] | None, module_name: str
    ) -> dict[str, Any]:
        """Encrypt the schema's ``format: secret`` leaves, bound to the module.

        This is the ordinary way a module's secret is written — the
        settings PUT — and it is where binding matters most. The owner is
        already in scope; it simply was not being used.
        """
        if not schema:
            return cleaned
        secret_paths = list(iter_secret_paths(schema))
        if not secret_paths:
            return cleaned
        return _encrypt_paths(cleaned, secret_paths, module_name)


def _refuse_if_platform_too_old(module_name: str) -> None:
    """Platform-version guard for tracked community modules.

    Best-effort: an unreadable tracking file or an untracked (core) module
    means no constraint. Modules installed before the guard existed have no
    ``inventari_min_version`` in their tracking entry — also no constraint.
    """
    try:
        entry = load_module_tracking().get(module_name)
    except Exception:  # noqa: BLE001 — tracking read must never block core modules
        return
    if not entry:
        return
    required = entry.get('inventari_min_version', '')
    if check_min_version(required):
        raise catalogue_refusal(
            'module_needs_newer_platform',
            module=module_name,
            required=required,
            current=get_platform_version(),
        )


#: Marks a key _encrypt_paths removed from the payload: the reader sent the
#: mask back, which means the field was left alone and the stored value must
#: survive untouched.
_DROP_KEY = object()


def _encrypt_paths(
    data: dict[str, Any], paths: list[tuple[str, ...]], module_name: str
) -> dict[str, Any]:
    """Return a shallow copy of *data* with secret leaves bound and encrypted.

    Walks each path tuple; if the leaf is a non-empty string, encrypts it
    against *module_name*. Empty / None leaves are left untouched (the
    caller chose to clear them). A leaf that IS the mask is dropped from the
    payload entirely: GET hands the mask out for "unchanged", and the
    settings round-trip sends it back — encrypting the literal would
    overwrite the real secret with ten asterisks.
    """

    def _walk(node: Any, path: tuple[str, ...]) -> Any:
        if not path:
            if isinstance(node, str) and node:
                if node == MASKED_VALUE:
                    return _DROP_KEY
                return encrypt_module_secret(module_name, node)
            return node
        head, *rest = path
        if not isinstance(node, dict) or head not in node:
            return node
        new_child = _walk(node[head], tuple(rest))
        if new_child is _DROP_KEY:
            new_node = {k: v for k, v in node.items() if k != head}
        else:
            new_node = {**node, head: new_child}
        if not new_node:
            # Nothing survived underneath: omit the whole group rather than
            # overwrite the stored group (and its other keys) with emptiness.
            return _DROP_KEY
        return new_node

    result: dict[str, Any] = {**data}
    for path in paths:
        walked = _walk(result, path)
        if walked is _DROP_KEY:
            result = {k: v for k, v in result.items() if k != path[0]}
        else:
            result = walked
    return result
