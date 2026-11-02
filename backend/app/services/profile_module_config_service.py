"""Applying a product profile's ``module_config`` — with a journal entry.

Two paths apply a profile to an organization: first-run onboarding
(``onboarding_service``) and a later switch (``profile_switch_service``).
Both wrote the declared configuration straight into ``organization.settings``,
so an organization could leave a switch with different approval thresholds
and warning windows while the journal named nothing but the profile id — and
the onboarding wizard named nothing at all.

The write is one shape and lives here once. The journal entry is built from
the same place and not from each caller: an audit trail every caller has to
remember is the shape that lost it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ContractViolationError, ValidationException
from app.core.logging import get_logger
from app.core.module_registry import module_registry
from app.core.settings_validator import (
    SchemaValidationError,
    validate_payload_against_schema,
)
from app.services.module_service import ModuleService

if TYPE_CHECKING:
    from app.models.organization import Organization

logger = get_logger(__name__)


async def apply_profile_module_config_async(
    db: AsyncSession,
    organization: Organization,
    module_config: Mapping[str, Mapping[str, Any]] | None,
    *,
    default_modules: Sequence[str],
    profile_id: str,
    user_id: UUID | None,
) -> list[str]:
    """Write a profile's per-module configuration, journaling what moved.

    Each namespace goes through the shared settings API and, when the stored
    values actually moved, earns the journal entry the settings screen
    already writes: the module as the target, the keys that changed with
    secret leaves masked. Configuration a module cannot take — a schema-less
    module, a value the schema refuses — is skipped with a warning, and the
    module is still enabled with its own defaults.

    ``user_id`` is the actor the entry is written under; ``None`` is the
    honest answer for the non-product callers and journals nothing under
    anybody's name.

    Returns the modules whose stored settings changed.
    """
    if not module_config:
        return []

    from app.core.public_api import core_api

    changed_modules: list[str] = []
    for module_name, raw_config in module_config.items():
        if module_name not in default_modules:
            logger.warning(
                'Profile %s declares module_config for %s but it is not '
                'in default_modules — skipping',
                profile_id,
                module_name,
            )
            continue

        instance = module_registry.get(module_name)
        schema = instance.get_settings_schema() if instance is not None else None
        if not schema:
            logger.debug(
                'Profile %s has config for %s but module declares no schema — skipping',
                profile_id,
                module_name,
            )
            continue

        try:
            cleaned = validate_payload_against_schema(raw_config, schema)
        except (SchemaValidationError, ContractViolationError) as exc:
            logger.warning(
                'Profile %s module_config for %s failed validation (%s) — skipping',
                profile_id,
                module_name,
                exc,
            )
            continue
        if not cleaned:
            continue

        namespace = f'module:{module_name}'
        before = copy.deepcopy((organization.settings or {}).get(namespace, {}))
        try:
            await core_api.settings.set_bulk_async(
                db, organization.id, module_name, cleaned
            )
        except ValidationException as exc:
            logger.warning(
                'Profile %s module_config for %s rejected (%s) — skipping',
                profile_id,
                module_name,
                exc.detail,
            )
            continue

        # ``set_bulk_async`` shallow-merges the payload into the namespace,
        # so the record it leaves behind is known here without re-reading it
        # — and without assuming the caller's instance is the one the
        # settings API happened to load.
        after = {**before, **cleaned}
        change = ModuleService.settings_change_snapshot(
            module_name, schema, before, after
        )
        if change is None:
            continue

        await core_api.audit_log.log_action_async(
            db,
            organization_id=organization.id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.MODULE,
            target_id=organization.id,
            # ``subject`` is what tells this entry from a hand edit of the
            # same namespace on the settings screen — the two write the
            # same keys and would otherwise read identically.
            snapshot={
                'name': module_name,
                'subject': f'profile:{profile_id}',
                **change,
            },
        )
        changed_modules.append(module_name)

    return changed_modules
