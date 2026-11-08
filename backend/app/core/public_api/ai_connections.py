"""CoreAPI surface for the AI Connections pool.

Per AGENTS.md §3 (Golden Path), the architecture linter forbids this
module from importing ORM models directly. Every read and write goes
through :class:`app.services.ai_connection_service.AiConnectionService`,
and the methods here translate public contract DTOs into service kwargs.

Scope:

- CRUD: list / create / update / delete a connection
- /purposes: list every registered purpose with the org's current
  binding UUID
- /bindings: set a purpose -> connection binding on org settings

The methods here are transaction-aware: writes call ``db.add()`` /
``db.flush()`` only — the caller (router) commits.
"""

from __future__ import annotations

import copy
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AiConnectionCreateDTO,
    AiConnectionDTO,
    AiConnectionUpdateDTO,
    AiPurposeDTO,
)
from app.core.exceptions import ServiceRejectionError
from app.core.llm.purpose_registry import all_purposes
from app.core.logging import get_logger
from app.core.public_api._access import reads, writes

if TYPE_CHECKING:
    from app.services.ai_connection_service import AiConnectionService

logger = get_logger(__name__)


class ConnectionStillBoundError(Exception):
    """Raised when a delete is attempted on a connection that's
    still the default for some declared purpose.

    The router maps this to HTTP 409.
    """


# Core features. The registry's owner_module is an
# attribution hint; per-purpose bindings (``settings.ai.defaults[<key>]``)
# are written for every purpose alike, so no routing split is needed here.


class CoreAIConnectionsAPI:
    """Public API used by the /api/v1/ai-connections router."""

    def __init__(self) -> None:
        self._service = _get_service()

    # -------- read paths -----------------------------------------------------

    @reads
    async def list_async(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> list[AiConnectionDTO]:
        schemas = await self._service.list_for_org(db, org_id)
        return [_schema_to_dto(s) for s in schemas]

    @reads
    async def get_async(
        self, db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID
    ) -> AiConnectionDTO | None:
        schema = await self._service.get_for_org(db, org_id, conn_id)
        return _schema_to_dto(schema) if schema else None

    @writes
    async def test_connection_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        *,
        connection_id: uuid.UUID | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model_name: str | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate credentials, then check the model against the contract."""
        result: dict[str, Any] = await self._service.test_connection(
            db,
            org_id,
            connection_id=connection_id,
            provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            capabilities=capabilities,
        )
        return result

    @reads
    async def list_purposes_async(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> list[AiPurposeDTO]:
        """All registered purposes, with the choice and the verdict apart.

        ``bound_connection_id`` is what the organization chose — the raw
        settings value, the same answer the binding select renders and the
        deletion guard protects. ``usable`` is the verdict — whether this
        purpose will actually run — built from the same pieces
        :func:`app.core.llm.registry.get_client_for_purpose` answers from:
        binding present, connection in this organization, capability
        carried, capability test not failed; or, with nothing chosen, the
        legacy env fallback. An earlier shape folded the verdict into the
        binding field, and a binding the rules refused then made the
        select forget the choice it was rendering. The promise sentences
        branch on ``usable`` and on nothing else.
        """
        from app.core.llm import registry

        settings_dict = await _get_settings_async(db, org_id) or {}
        result: list[AiPurposeDTO] = []

        for spec in all_purposes():
            bound_uuid = registry.binding_from_settings(
                settings_dict, spec.key, spec.owner_module
            )
            if bound_uuid is not None:
                served = await registry.connection_serves_async(
                    db, org_id, bound_uuid, spec.key
                )
                usable = served is not None
            else:
                usable = registry.env_fallback_serves(spec.key)

            result.append(
                AiPurposeDTO(
                    key=spec.key,
                    capability=spec.capability,
                    label_key=spec.label_key,
                    description_key=spec.description_key,
                    owner_module=spec.owner_module,
                    bound_connection_id=bound_uuid,
                    usable=usable,
                )
            )
        return result

    # -------- write paths ----------------------------------------------------

    @writes
    async def create_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        data: AiConnectionCreateDTO,
    ) -> AiConnectionDTO:
        from app.core.llm.enums import LlmCapability

        caps = [LlmCapability(c) for c in data.capabilities]
        schema = await self._service.create(
            db,
            org_id,
            name=data.name,
            provider=data.provider,
            api_key=data.api_key,
            api_base_url=data.api_base_url,
            model_name=data.model_name,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            top_p=data.top_p,
            capabilities=caps,
        )
        return _schema_to_dto(schema)

    @writes
    async def update_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        conn_id: uuid.UUID,
        data: AiConnectionUpdateDTO,
    ) -> AiConnectionDTO | None:
        from app.core.llm.enums import LlmCapability
        from app.services.ai_connection_service import UNSET
        from app.services.crypto_service import MASKED_VALUE

        masked_marker = data.api_key == MASKED_VALUE
        # Presence is decided here, while the payload's key set is still
        # visible: an absent key travels as UNSET and never reaches a column,
        # a carried null is the caller's instruction to clear (AGENTS.md §2b).
        sent = data.model_fields_set

        caps: Any = UNSET
        if 'capabilities' in sent:
            caps = (
                [LlmCapability(c) for c in data.capabilities]
                if data.capabilities is not None
                else None
            )

        schema = await self._service.update(
            db,
            org_id,
            conn_id,
            new_api_key=data.api_key if 'api_key' in sent else UNSET,
            masked_marker=masked_marker,
            name=data.name if 'name' in sent else UNSET,
            api_base_url=data.api_base_url if 'api_base_url' in sent else UNSET,
            model_name=data.model_name if 'model_name' in sent else UNSET,
            temperature=data.temperature if 'temperature' in sent else UNSET,
            max_tokens=data.max_tokens if 'max_tokens' in sent else UNSET,
            top_p=data.top_p if 'top_p' in sent else UNSET,
            capabilities=caps,
        )
        return _schema_to_dto(schema) if schema else None

    @writes
    async def delete_async(
        self, db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID
    ) -> bool:
        """Delete a connection. Refuses with
        :class:`ConnectionStillBoundError` when the row is still the
        default for some registered purpose. The refusal text comes from
        the error catalog in the reader's language — a UUID-bearing
        English sentence is what a Polish session used to get here."""
        if await self._service.is_bound_to_any_purpose(db, org_id, conn_id):
            from app.i18n.service import get_current_lang, get_error_message

            raise ConnectionStillBoundError(
                get_error_message('ai_connection_still_bound', get_current_lang())
            )
        deleted: bool = await self._service.delete(db, org_id, conn_id)
        return deleted

    @writes
    async def set_binding_async(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        purpose_key: str,
        connection_id: uuid.UUID | None,
    ) -> None:
        """Set *purpose_key* -> *connection_id* for *org_id*.

        ``connection_id=None`` clears the binding.

        The settings dict is deep-copied before any mutation: the read path
        (``decrypt_settings``) returns a SHALLOW copy that shares nested
        dicts with the ORM-tracked ``Organization.settings`` value. Mutating
        those nested dicts in place makes the later assignment compare equal
        to the already-mutated tracked value, so SQLAlchemy records no
        change and emits no UPDATE — the first bind persisted (it added a
        new top-level key) while every rebind was silently lost.
        """
        from app.core.llm.purpose_registry import all_purposes, get_purpose

        spec = get_purpose(purpose_key)
        if spec is None:
            raise ServiceRejectionError('ai_purpose_unknown', purpose=purpose_key)

        settings = copy.deepcopy(await _get_settings_async(db, org_id) or {})

        # Per purpose key, whatever the owner module. The module-owned slot
        # (``settings.modules.<owner>.ai_default_connection_id``) was one id
        # per module, which worked while every module had exactly one
        # purpose — a second one (recipes reads pages and parses text)
        # would have its binding silently re-route the first. Writing only
        # ``ai.defaults`` left that slot answering: a clear (null) came
        # back as the same connection, because the read path
        # (:func:`binding_from_settings`) still fell back to the slot. So
        # the first write through here carries the slot across — every
        # purpose of the module that was reading it gets the same id under
        # its own key (nothing the org sees changes), the slot itself is
        # dropped, and the requested write then lands where the reader
        # reads. Blindly clearing the slot would release the sibling
        # purposes the org never touched; carrying it across releases
        # no one.
        module_settings = (settings.get('modules') or {}).get(spec.owner_module)
        defaults = settings.setdefault('ai', {}).setdefault('defaults', {})
        if isinstance(module_settings, dict) and module_settings.get(
            'ai_default_connection_id'
        ):
            legacy_slot = module_settings['ai_default_connection_id']
            for other in all_purposes():
                if other.owner_module != spec.owner_module or other.key == purpose_key:
                    continue
                if not defaults.get(other.key):
                    defaults[other.key] = str(legacy_slot)
            module_settings.pop('ai_default_connection_id', None)
        if connection_id is None:
            defaults.pop(purpose_key, None)
        else:
            defaults[purpose_key] = str(connection_id)

        await _persist_org_settings(db, org_id, settings)


# ----------------------------------------------------------------------
# Mapping helpers — convert AiConnectionSchema to AiConnectionDTO.
# ----------------------------------------------------------------------


def _get_service() -> AiConnectionService:
    """Lazy import to avoid module-level dependency on the service."""
    from app.services.ai_connection_service import AiConnectionService

    return AiConnectionService()


def _schema_to_dto(schema: Any) -> AiConnectionDTO:
    """Map an AiConnectionSchema (service output) to AiConnectionDTO."""
    return AiConnectionDTO(
        id=schema.id,
        name=schema.name,
        provider=str(schema.provider),
        api_key=schema.api_key,
        api_base_url=schema.api_base_url,
        model_name=schema.model_name,
        temperature=schema.temperature,
        max_tokens=schema.max_tokens,
        top_p=schema.top_p,
        capabilities=[str(c) for c in schema.capabilities],
        capability_checks={
            capability: check.model_dump(mode='json')
            for capability, check in (schema.capability_checks or {}).items()
        },
        created_at=schema.created_at,
        updated_at=schema.updated_at,
    )


# ----------------------------------------------------------------------
# Settings helpers — minimal CoreAPI logic that doesn't fit the service.
# ----------------------------------------------------------------------


async def _get_settings_async(
    db: AsyncSession, org_id: uuid.UUID
) -> dict[str, Any] | None:
    from app.core.public_api import core_api

    return await core_api.organizations.get_settings_async(db, org_id)


async def _persist_org_settings(
    db: AsyncSession,
    org_id: uuid.UUID,
    settings: dict[str, Any],
) -> None:
    from app.services._org_reads import get_by_id_async
    from app.services.crypto_service import merge_incoming_settings

    org = await get_by_id_async(db, org_id)
    if org is None:
        raise ServiceRejectionError('organization_not_found')
    org.settings = merge_incoming_settings(settings, org.settings or {})
    await db.flush()
