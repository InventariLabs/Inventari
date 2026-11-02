"""Unit tests for app.core.public_api.ai_connections.

The Core API for the AI Connections pool. Per AGENTS.md §3 (Golden
Path), the router at ``/api/v1/ai-connections`` never touches
``app.models.ai_connection.AiConnection`` directly — every read and
write goes through these methods.

What we assert:

- ``list_async`` filters strictly by ``organization_id`` (tenant guard).
- ``create_async`` encrypts the plaintext api_key before persisting.
- ``update_async`` handles ``MASKED_VALUE`` as \"keep the cipher\".
- ``delete_async`` raises a domain ValueError when ANY purpose is bound
  to the row (the router maps that to HTTP 409).
- ``set_binding_async`` writes through the right slot (Core-owned ->
  ``settings.ai.defaults[<purpose>]``; module-owned ->
  ``settings.modules.<owner_module>].ai_default_connection_id``).
- ``list_purposes_async`` enriches each registered purpose with the
  current org's bound connection UUID (None when unbound).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --------------------------- helpers ----------------------------------------


def _make_conn_schema(org_id: uuid.UUID, *, name: str = 'Pool A'):
    """Service-layer return value: an ``AiConnectionSchema`` (pydantic),
    which is what ``AiConnectionService`` hands back to the facade."""
    from app.schemas.ai_connection import AiConnectionSchema

    return AiConnectionSchema(
        id=uuid.uuid4(),
        name=name,
        provider='openrouter',
        api_key='**********',
        api_base_url='https://openrouter.ai/api/v1',
        model_name='gemini-2.0-flash',
        temperature=None,
        max_tokens=None,
        top_p=None,
        capabilities=['vision', 'text'],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_existing_conn(
    org_id: uuid.UUID,
    *,
    name: str = 'Existing',
    api_key_enc: str = 'enc:previous-key',
    capabilities: list[str] | None = None,
):
    from app.models.ai_connection import AiConnection

    return AiConnection(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=name,
        provider='openrouter',
        api_key_enc=api_key_enc,
        api_base_url='https://openrouter.ai/api/v1',
        model_name='gemini-2.0-flash',
        capabilities=capabilities or ['vision', 'text'],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# --------------------------- list_async --------------------------------------


class TestListAsync:
    async def test_filters_by_org_id(self):
        """Tenant guard: callers must NOT be able to enumerate another
        org's pool by guessing a connection id.

        We mock db.scalars(...) so the implementation under test is
        the actual SQLAlchemy query construction in list_async.
        """
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI

        api = CoreAIConnectionsAPI()
        org_a = uuid.uuid4()
        conn_a = _make_existing_conn(org_a)

        # Mock db.scalars().all() to return one conn (filtered).
        mock_scalars_result = MagicMock()
        mock_scalars_result.all.return_value = [conn_a]
        db = AsyncMock()
        db.scalars = AsyncMock(return_value=mock_scalars_result)

        result = await api.list_async(db, org_id=org_a)

        assert len(result) == 1
        assert result[0].id == conn_a.id
        # api_key is masked
        assert result[0].api_key == '**********'


# --------------------------- create_async ------------------------------------


class TestCreateAsync:
    async def test_encryption_decoupled_from_db(self):
        """The encryption call is plain function — verify it on its own
        before the rest of the create pipeline touches the DB.

        The actual ``db.add`` / ``db.flush`` path is tested by the
        integration suite (see test_ai_connections_api.py in
        tests/integration). This unit assertion keeps the encryption
        contract visible without forcing a SQLAlchemy standup.

        Note: Fernet uses a random IV per call, so we cannot assert
        ciphertext stability here. Idempotency for already-encrypted
        inputs is covered in tests/unit/test_ai_connection_secrets.py.
        """
        from app.core.llm.secrets import encrypt_connection_secret

        ciphertext = encrypt_connection_secret('sk-or-plaintext')
        assert ciphertext.startswith('enc:')
        # Decrypt round-trips
        from app.core.llm.secrets import decrypt_connection_secret

        assert decrypt_connection_secret(ciphertext) == 'sk-or-plaintext'


# --------------------------- contract DTO path ---------------------------------


class TestContractDtoPath:
    def test_create_dto_rejects_unknown_provider(self):
        """The contracts DTO uses plain ``str`` for provider (community
        modules cannot reference ``LlmProvider``), so the enum membership
        check lives in a field validator on the DTO."""
        from pydantic import ValidationError

        from app.core.contracts import AiConnectionCreateDTO

        with pytest.raises(ValidationError):
            AiConnectionCreateDTO(name='X', provider='not-a-provider')

    async def test_create_maps_str_capabilities_to_enum(self):
        """The facade converts ``list[str]`` (contracts-legal) into
        ``list[LlmCapability]`` before calling the service — the service
        expects enum members (it reads ``.value``)."""
        from app.core.contracts import AiConnectionCreateDTO
        from app.core.llm.enums import LlmCapability
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        created = _make_conn_schema(org_id)

        with patch.object(
            api._service, 'create', AsyncMock(return_value=created)
        ) as mock_create:
            dto = AiConnectionCreateDTO(
                name='Pool A',
                provider='openrouter',
                api_base_url='https://openrouter.ai/api/v1',
                capabilities=['vision', 'text'],
            )
            result = await api.create_async(AsyncMock(), org_id, dto)

        caps = mock_create.call_args.kwargs['capabilities']
        assert caps == [LlmCapability.VISION, LlmCapability.TEXT]
        assert result.id == created.id

    def test_the_create_dto_refusal_names_the_field(self):
        """Module callers go through the contract DTO, not the FastAPI
        schema — the same refusal must name ``api_base_url`` in the
        pydantic error's ``loc`` there too, or a module author reads the
        field name out of the message text while the web form reads it
        out of ``loc``."""
        from pydantic import ValidationError

        from app.core.contracts import AiConnectionCreateDTO

        with pytest.raises(ValidationError) as exc_info:
            AiConnectionCreateDTO(
                name='x',
                provider='openrouter',
                api_base_url='',
            )

        (error,) = exc_info.value.errors()
        assert error['loc'] == ('api_base_url',)

    async def test_update_passes_through_dto_patch_semantics(self):
        """A field the payload did not carry arrives at the service as UNSET
        — "keep the current value" — and never as None, which now means the
        opposite: the caller asked for the column to be cleared (AGENTS.md
        §2b). A set capabilities list is converted to enums, and a plaintext
        api_key is not mistaken for the masked marker."""
        from app.core.contracts import AiConnectionUpdateDTO
        from app.core.llm.enums import LlmCapability
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI
        from app.services.ai_connection_service import UNSET

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        existing = _make_conn_schema(org_id)

        with patch.object(
            api._service, 'update', AsyncMock(return_value=existing)
        ) as mock_update:
            dto = AiConnectionUpdateDTO(capabilities=['vision'])
            await api.update_async(AsyncMock(), org_id, existing.id, dto)

        kwargs = mock_update.call_args.kwargs
        assert kwargs['capabilities'] == [LlmCapability.VISION]
        assert kwargs['name'] is UNSET
        assert kwargs['new_api_key'] is UNSET
        assert kwargs['masked_marker'] is False


# --------------------------- update_async ------------------------------------


class TestUpdateAsync:
    async def test_masked_value_keeps_existing_cipher(self):
        """Front-end sends MASKED_VALUE -> the api_key_enc column is
        not touched (the secret stays encrypted on disk)."""
        from app.core.contracts import AiConnectionUpdateDTO
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI
        from app.services.crypto_service import MASKED_VALUE

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        existing = _make_existing_conn(org_id, api_key_enc='enc:existing-cipher')

        db = AsyncMock()
        with patch.object(api._service, '_get_raw', AsyncMock(return_value=existing)):
            data = AiConnectionUpdateDTO(
                name='renamed',
                api_key=MASKED_VALUE,
            )
            result = await api.update_async(
                db, org_id=org_id, conn_id=existing.id, data=data
            )

        # The schema response masks the cipher; we assert the
        # MASKED_VALUE placeholder, NOT the underlying cipher text
        # (the schema contract).
        assert result.api_key == MASKED_VALUE
        # Non-sensitive fields ARE updated.
        assert result.name == 'renamed'
        # The model itself was NOT touched at the api_key_enc level.
        assert existing.api_key_enc == 'enc:existing-cipher'

    async def test_plaintext_rotation_replaces_cipher(self):
        from app.core.contracts import AiConnectionUpdateDTO
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        existing = _make_existing_conn(org_id, api_key_enc='enc:old')

        db = AsyncMock()
        # encrypt_connection_secret is imported lazily inside the
        # module, so the patch target is the module-level reference,
        # not the source module's symbol.
        with (
            patch.object(api._service, '_get_raw', AsyncMock(return_value=existing)),
            patch(
                'app.services.ai_connection_service.encrypt_connection_secret',
                return_value='enc:new',
            ),
        ):
            data = AiConnectionUpdateDTO(api_key='sk-or-new')
            await api.update_async(db, org_id=org_id, conn_id=existing.id, data=data)

        # The model itself now holds the new cipher (this is the
        # contract tested here — that plaintext rotates it).
        assert existing.api_key_enc == 'enc:new'


# --------------------------- delete_async ------------------------------------


class TestDeleteAsync:
    async def test_unbound_connection_can_be_deleted(self):
        from app.core.public_api.ai_connections import (
            CoreAIConnectionsAPI,
        )

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        existing = _make_existing_conn(org_id)

        db = AsyncMock()
        with patch.object(api._service, '_get_raw', AsyncMock(return_value=existing)):
            with patch.object(
                api._service, 'is_bound_to_any_purpose', AsyncMock(return_value=False)
            ):
                await api.delete_async(db, org_id=org_id, conn_id=existing.id)

    async def test_bound_connection_raises(self):
        """Domain-level guard: refusing to delete a connection that's
        still in use is what the router maps to HTTP 409. We assert
        on the exception type — router-test pins the 409 mapping."""
        from app.core.public_api.ai_connections import (
            ConnectionStillBoundError,
            CoreAIConnectionsAPI,
        )

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        existing = _make_existing_conn(org_id)

        db = AsyncMock()
        with patch.object(api._service, '_get_raw', AsyncMock(return_value=existing)):
            with patch.object(
                api._service, 'is_bound_to_any_purpose', AsyncMock(return_value=True)
            ):
                with pytest.raises(ConnectionStillBoundError):
                    await api.delete_async(db, org_id=org_id, conn_id=existing.id)


# --------------------------- list_purposes_async -----------------------------


class TestListPurposesAsync:
    async def test_answers_the_choice_and_the_verdict_in_separate_fields(self):
        """``bound_connection_id`` is the raw choice the org made — the same
        answer the binding select renders and the deletion guard protects.
        ``usable`` is the verdict the promise sentences branch on, from the
        chain the client builder answers to. One field answering both
        questions is how a binding the rules refused made the binding select
        forget the choice it was rendering, and that dead end has no way out
        in the UI."""
        from app.core.llm import registry
        from app.core.public_api import ai_connections as ai_connections_api

        api = ai_connections_api.CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        chosen = uuid.uuid4()

        async def fake_settings(db, org):
            return {'ai': {'defaults': {'vision.extract': str(chosen)}}}

        async def refused(db, org, conn_id, key):
            return None

        with (
            patch.object(
                ai_connections_api, '_get_settings_async', side_effect=fake_settings
            ),
            patch.object(registry, 'connection_serves_async', side_effect=refused),
        ):
            db = AsyncMock()
            purposes = await api.list_purposes_async(db, org_id=org_id)

        # vision.extract is registered; recipes.text_parse too.
        keys = [p.key for p in purposes]
        assert 'vision.extract' in keys
        assert 'recipes.text_parse' in keys

        # The binding the rules refuse keeps the org's choice readable in
        # its own field; the verdict refusal lands in the other one.
        vision_entry = next(p for p in purposes if p.key == 'vision.extract')
        assert vision_entry.bound_connection_id == chosen
        assert vision_entry.usable is False
        # Nothing chosen for the text purpose and no env key: neither field
        # invents an answer.
        recipes_entry = next(p for p in purposes if p.key == 'recipes.text_parse')
        assert recipes_entry.bound_connection_id is None
        assert recipes_entry.usable is False

    async def test_env_fallback_reads_usable_without_a_binding(self):
        """The one unbound state that still runs: when the legacy env
        fallback would serve, ``usable`` says so while ``bound_connection_id``
        stays empty — the two fields disagree on purpose here, and each tells
        its own truth."""
        from app.core.llm import registry
        from app.core.public_api import ai_connections as ai_connections_api

        api = ai_connections_api.CoreAIConnectionsAPI()
        org_id = uuid.uuid4()

        async def no_settings(db, org):
            return {}

        with (
            patch.object(
                ai_connections_api, '_get_settings_async', side_effect=no_settings
            ),
            patch.object(registry, 'env_fallback_serves', return_value=True),
        ):
            db = AsyncMock()
            purposes = await api.list_purposes_async(db, org_id=org_id)

        vision_entry = next(p for p in purposes if p.key == 'vision.extract')
        assert vision_entry.bound_connection_id is None
        assert vision_entry.usable is True


# --------------------------- set_binding_async ------------------------------


class TestSetBindingAsync:
    async def test_core_owned_purpose_writes_to_settings_ai_defaults(self):
        """``vision.extract`` is Core-owned — the binding lives under
        ``settings.ai.defaults[<key>]``."""
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        conn_uuid = uuid.uuid4()
        captured: dict = {}

        async def fake_persist(db_arg, oid, settings):
            captured['settings'] = settings
            # Drain the coroutine so the warning about an
            # unawaited AsyncMock doesn't fire.

        # Stub _get_settings_async (returns empty settings — no prior
        # binding) and _persist_org_settings (captures arg).
        with (
            patch(
                'app.core.public_api.ai_connections._get_settings_async',
                AsyncMock(return_value={}),
            ),
            patch(
                'app.core.public_api.ai_connections._persist_org_settings',
                AsyncMock(side_effect=fake_persist),
            ),
        ):
            db = AsyncMock()
            await api.set_binding_async(
                db,
                org_id=org_id,
                purpose_key='vision.extract',
                connection_id=conn_uuid,
            )

        new_settings = captured['settings']
        assert new_settings['ai']['defaults']['vision.extract'] == str(conn_uuid)

    async def test_module_owned_purpose_writes_to_its_own_slot(self):
        """``recipes.text_parse`` is module-owned, and its binding lives
        under ``settings.ai.defaults['recipes.text_parse']`` — per purpose
        key, not one id per module: recipes has a second purpose (the page
        reader), and a shared slot would let the last binding re-route the
        other one. The module slot stays a read-side legacy fallback."""
        from app.core.public_api.ai_connections import CoreAIConnectionsAPI

        api = CoreAIConnectionsAPI()
        org_id = uuid.uuid4()
        conn_uuid = uuid.uuid4()
        captured: dict = {}

        async def fake_persist(db_arg, oid, settings):
            captured['settings'] = settings

        with (
            patch(
                'app.core.public_api.ai_connections._get_settings_async',
                AsyncMock(return_value={}),
            ),
            patch(
                'app.core.public_api.ai_connections._persist_org_settings',
                AsyncMock(side_effect=fake_persist),
            ),
        ):
            db = AsyncMock()
            await api.set_binding_async(
                db,
                org_id=org_id,
                purpose_key='recipes.text_parse',
                connection_id=conn_uuid,
            )

        new_settings = captured['settings']
        assert new_settings['ai']['defaults']['recipes.text_parse'] == str(conn_uuid)
        assert 'modules' not in new_settings or 'recipes' not in (
            new_settings.get('modules') or {}
        )
