"""Unit tests for app.core.llm.registry.

The resolver (``get_client_for_purpose``) is the single seam that
turns a high-level purpose key into a working LLM client. It has
several non-trivial branches that need pinning:

- Unknown purpose key -> ``None`` (caller decides what to do).
- No binding yet for an org's purpose -> legacy env-var fallback
  returns a transient client only when ``LLM_API_KEY`` is set.
- Binding points to a connection in another org -> rejected (tenant
  guard starts at the row level).
- Connection does not declare the purpose's required capability ->
  rejected (caller may surface a clear UI error).
- Connection exists + has the capability -> delegated to ``factory.get_client``.

The Core-vs-Module routing: a Core-owned purpose (e.g. ``vision.extract``)
reads its binding from ``settings.ai.defaults[<purpose>]``; a
module-owned purpose (e.g. ``recipes.text_parse``) reads from
``settings.modules.<owner_module>.ai_default_connection_id``. We pin
both paths.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

# ---------- helpers -----------------------------------------------------------


def _make_connection(
    *,
    organization_id: uuid.UUID,
    provider: str = 'openrouter',
    capabilities: list[str] | None = None,
    model_name: str = 'gemini-2.0-flash',
):
    from app.models.ai_connection import AiConnection

    return AiConnection(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name='Test Conn',
        provider=provider,
        api_key_enc='enc:test-key',
        api_base_url='https://openrouter.ai/api/v1',
        model_name=model_name,
        capabilities=capabilities or ['vision', 'text'],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------- behaviour --------------------------------------------------------


class TestGetClientForPurposeUnknownPurpose:
    async def test_unknown_purpose_key_returns_none(self):
        from app.core.llm.registry import get_client_for_purpose

        db = AsyncMock()
        result = await get_client_for_purpose(
            db,
            org_id=uuid.uuid4(),
            purpose_key='does.not.exist',
        )
        assert result is None


class TestGetClientForPurposeWithBinding:
    async def test_core_owned_purpose_resolves_via_settings_defaults(self):
        """``vision.extract`` is Core-owned — the binding lives in
        ``settings.ai.defaults[\"vision.extract\"]``."""

        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id)

        # Decrypted settings as the router would hand them to the resolver.
        settings = {
            'ai': {
                'defaults': {
                    'vision.extract': str(conn.id),
                }
            }
        }
        get_settings_mock = AsyncMock(return_value=settings)

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                get_settings_mock,
            ),
            patch(
                'app.core.llm.registry._get_connection',
                AsyncMock(return_value=conn),
            ),
        ):
            from app.core.llm.registry import get_client_for_purpose as gcfp

            db = AsyncMock()
            result = await gcfp(db, org_id=org_id, purpose_key='vision.extract')

        assert result is not None
        from app.core.llm.openai_client import OpenAiCompatibleClient

        assert isinstance(result, OpenAiCompatibleClient)

    async def test_module_owned_purpose_resolves_via_module_settings(self):
        """``recipes.text_parse`` is module-owned — the binding lives in
        ``settings.modules.recipes.ai_default_connection_id``."""

        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id)

        # No 'ai.defaults' key — the resolver must look in the module slot.
        settings = {
            'modules': {
                'recipes': {
                    'ai_default_connection_id': str(conn.id),
                }
            }
        }
        get_settings_mock = AsyncMock(return_value=settings)

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                get_settings_mock,
            ),
            patch(
                'app.core.llm.registry._get_connection',
                AsyncMock(return_value=conn),
            ),
        ):
            from app.core.llm.registry import get_client_for_purpose as gcfp

            db = AsyncMock()
            result = await gcfp(db, org_id=org_id, purpose_key='recipes.text_parse')

        assert result is not None

    async def test_no_binding_returns_none(self):
        """Org exists, settings are empty, no env var -> None."""
        from app.core.llm.registry import get_client_for_purpose

        get_settings_mock = AsyncMock(return_value={})

        with patch(
            'app.core.public_api.core_api.organizations.get_settings_async',
            get_settings_mock,
        ):
            result = await get_client_for_purpose(
                AsyncMock(),
                org_id=uuid.uuid4(),
                purpose_key='vision.extract',
            )
        assert result is None


class TestCapabilityMismatch:
    async def test_connection_missing_capability_returns_none(self):
        """If a text-only connection is bound to a VISION purpose, the
        resolver must refuse rather than silently downgrade."""
        from app.core.llm.registry import get_client_for_purpose

        org_id = uuid.uuid4()
        # Text-only connection bound to a vision purpose.
        conn = _make_connection(
            organization_id=org_id,
            capabilities=['text'],  # no 'vision'
        )
        settings = {'ai': {'defaults': {'vision.extract': str(conn.id)}}}

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                AsyncMock(return_value=settings),
            ),
            patch(
                'app.core.llm.registry._get_connection',
                AsyncMock(return_value=conn),
            ),
        ):
            db = AsyncMock()
            result = await get_client_for_purpose(
                db, org_id=org_id, purpose_key='vision.extract'
            )
        assert result is None


class TestCrossOrgSecurity:
    async def test_connection_in_other_org_rejected(self):
        """Tenant guard: a row that belongs to org A is invisible to
        org B even if the binding string points at its UUID.
        Without this, a tenant could discover or invoke a neighbor's
        provider API key via crafted settings."""
        from app.core.llm.registry import get_client_for_purpose

        # Connection belongs to org A.
        real_org_id = uuid.uuid4()
        attacker_org_id = uuid.uuid4()
        conn = _make_connection(organization_id=real_org_id)

        # AttackerOrg's settings list the connection's UUID.
        settings = {'ai': {'defaults': {'vision.extract': str(conn.id)}}}

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                AsyncMock(return_value=settings),
            ),
            patch(
                'app.core.llm.registry._get_connection',
                AsyncMock(return_value=conn),
            ),
        ):
            db = AsyncMock()
            result = await get_client_for_purpose(
                db,
                org_id=attacker_org_id,
                purpose_key='vision.extract',
            )
        assert result is None


class TestLegacyEnvFallback:
    """When no DB binding exists yet (fresh install, pre-migration
    env-var setup), the resolver falls back to LLM_API_KEY so
    existing self-hosted installs keep working until the migration
    runs.

    NOTE on patching: ``app.config.settings`` is a pydantic-settings
    instance whose values are read at startup. ``monkeypatch.setenv``
    does NOT update the cached value, so we patch the attribute on
    the settings instance directly. Production callers never see this
    distinction because they don't swap the env at runtime.
    """

    def _patch_settings(
        self,
        monkeypatch,
        *,
        openrouter_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str = 'openrouter',
        capabilities: str = '',
    ) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_API_KEY', openrouter_key, raising=False)
        monkeypatch.setattr(settings, 'LLM_PROVIDER', provider, raising=False)
        monkeypatch.setattr(settings, 'LLM_CAPABILITIES', capabilities, raising=False)
        if base_url is not None:
            monkeypatch.setattr(settings, 'LLM_API_BASE_URL', base_url, raising=False)
        if model is not None:
            monkeypatch.setattr(settings, 'LLM_MODEL', model, raising=False)

    async def test_no_env_var_returns_none(self, monkeypatch):
        from app.core.llm.registry import get_client_for_purpose

        self._patch_settings(monkeypatch, openrouter_key=None)

        with patch(
            'app.core.public_api.core_api.organizations.get_settings_async',
            AsyncMock(return_value={}),
        ):
            result = await get_client_for_purpose(
                AsyncMock(),
                org_id=uuid.uuid4(),
                purpose_key='vision.extract',
            )
        assert result is None

    async def test_openrouter_key_set_returns_transient_client(self, monkeypatch):
        """Bare-env installs: LLM_API_KEY alone yields a client
        without a DB row, so calls succeed until the migration runs."""
        from app.core.llm.openai_client import OpenAiCompatibleClient
        from app.core.llm.registry import get_client_for_purpose

        self._patch_settings(
            monkeypatch,
            openrouter_key='sk-or-bare-env',
            base_url='https://openrouter.ai/api/v1',
            model='gemini-2.0-flash',
        )

        with patch(
            'app.core.public_api.core_api.organizations.get_settings_async',
            AsyncMock(return_value={}),
        ):
            client = await get_client_for_purpose(
                AsyncMock(),
                org_id=uuid.uuid4(),
                purpose_key='vision.extract',
            )
        assert isinstance(client, OpenAiCompatibleClient)
        # The transient connection should hold the env-derived key so
        # the request actually succeeds.
        assert client._conn.api_key_enc  # populated by fallback

    async def _resolve(self, purpose_key: str):
        from app.core.llm.registry import get_client_for_purpose

        with patch(
            'app.core.public_api.core_api.organizations.get_settings_async',
            AsyncMock(return_value={}),
        ):
            return await get_client_for_purpose(
                AsyncMock(), org_id=uuid.uuid4(), purpose_key=purpose_key
            )

    @pytest.mark.parametrize(
        ('provider', 'base_url', 'model'),
        [
            ('deepseek', 'https://api.deepseek.com', 'deepseek-flash'),
            ('mimo', 'https://api.xiaomimimo.com/v1', 'mimo-v2.6-flash'),
        ],
    )
    async def test_the_provider_comes_from_the_environment(
        self, monkeypatch, provider, base_url, model
    ):
        """A DeepSeek or MiMo key in .env reaches its own provider, at
        its own address — not OpenRouter's, which would refuse the key."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        self._patch_settings(
            monkeypatch,
            openrouter_key='sk-provider-key',
            base_url=base_url,
            model=model,
            provider=provider,
        )

        client = await self._resolve('recipes.text_parse')

        assert isinstance(client, OpenAiCompatibleClient)
        assert client.connection_provider == provider
        assert client._conn.api_base_url == base_url
        assert client.model_name == model

    async def test_a_text_only_model_is_not_handed_a_photograph(
        self, monkeypatch, caplog
    ):
        """Refused before the call, by name, instead of failing inside it
        with whatever the provider says about an image it cannot read."""
        from app.core.llm.registry import env_fallback_serves

        self._patch_settings(
            monkeypatch,
            openrouter_key='sk-provider-key',
            base_url='https://api.deepseek.com',
            model='deepseek-flash',
            provider='deepseek',
            capabilities='text',
        )

        assert await self._resolve('vision.extract') is None
        assert env_fallback_serves('vision.extract') is False
        assert 'LLM_CAPABILITIES' in caplog.text
        # The same environment still serves what it was declared for.
        assert await self._resolve('recipes.text_parse') is not None
        assert env_fallback_serves('recipes.text_parse') is True

    async def test_the_transient_connection_claims_only_what_was_declared(
        self, monkeypatch
    ):
        self._patch_settings(
            monkeypatch,
            openrouter_key='sk-provider-key',
            base_url='https://api.xiaomimimo.com/v1',
            provider='mimo',
            capabilities='text,vision',
        )

        client = await self._resolve('vision.extract')

        assert sorted(client._conn.capabilities) == ['text', 'vision']

    def test_a_reader_purpose_is_not_promised_by_a_model_key(self, monkeypatch):
        """The page reader never builds a client from the environment
        (get_connection_for_purpose), so the purposes list must not say
        the environment serves it."""
        from app.core.llm.registry import env_fallback_serves

        self._patch_settings(monkeypatch, openrouter_key='sk-or-bare-env')

        assert env_fallback_serves('recipes.url_fetch') is False


class TestACapabilityThatFailedItsTest:
    """The claim is not the last word.

    ``capabilities`` says what somebody ticked — often the form, off the
    provider's name rather than off the model. The connection test asks the
    model to do the job and judges the answer; a connection whose vision test
    came back failed has no business being handed out for reading photographs.
    """

    async def _resolve(self, conn, purpose_key='vision.extract'):
        from app.core.llm.registry import get_client_for_purpose

        settings = {'ai': {'defaults': {purpose_key: str(conn.id)}}}
        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                AsyncMock(return_value=settings),
            ),
            patch(
                'app.core.llm.registry._get_connection',
                AsyncMock(return_value=conn),
            ),
        ):
            return await get_client_for_purpose(
                AsyncMock(), org_id=conn.organization_id, purpose_key=purpose_key
            )

    async def test_a_recorded_failure_takes_the_connection_off_the_list(self):
        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id, capabilities=['vision'])
        conn.capability_checks = {'vision': {'ok': False, 'at': '2026-08-27T10:00:00'}}

        assert await self._resolve(conn) is None

    async def test_a_recorded_pass_leaves_it_where_it_was(self):
        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id, capabilities=['vision'])
        conn.capability_checks = {'vision': {'ok': True, 'at': '2026-08-27T10:00:00'}}

        assert await self._resolve(conn) is not None

    async def test_never_tested_is_not_the_same_as_failed(self):
        """Every connection that predates the test is untested. Refusing those
        would take image recognition away from everyone who has not pressed
        Test since upgrading."""
        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id, capabilities=['vision'])
        conn.capability_checks = {}

        assert await self._resolve(conn) is not None

    async def test_a_failure_on_another_capability_does_not_count(self):
        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id, capabilities=['vision', 'text'])
        conn.capability_checks = {'text': {'ok': False, 'at': '2026-08-27T10:00:00'}}

        assert await self._resolve(conn) is not None


class TestOneReadPerAnswer:
    """The builder loads the settings once and the connection once — on
    the success path and on every refusal.

    An earlier shape routed the builder through the verdict helper, which
    re-read the same settings and re-loaded the same row; the doubling was
    invisible to every functional test. The counts here keep the chain
    honest: one question to settings, one load of the row, no third read.
    """

    async def test_success_path_reads_settings_and_connection_once(self):
        org_id = uuid.uuid4()
        conn = _make_connection(organization_id=org_id)
        settings = {'ai': {'defaults': {'vision.extract': str(conn.id)}}}

        get_settings_mock = AsyncMock(return_value=settings)
        get_connection_mock = AsyncMock(return_value=conn)

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                get_settings_mock,
            ),
            patch(
                'app.core.llm.registry._get_connection',
                get_connection_mock,
            ),
        ):
            from app.core.llm.registry import get_client_for_purpose

            await get_client_for_purpose(
                AsyncMock(), org_id=org_id, purpose_key='vision.extract'
            )

        assert get_settings_mock.await_count == 1
        assert get_connection_mock.await_count == 1

    async def test_refused_connection_does_not_re_read_the_settings(self):
        org_id = uuid.uuid4()
        conn = _make_connection(
            organization_id=org_id,
            capabilities=['text'],  # bound to a vision purpose -> refused
        )
        settings = {'ai': {'defaults': {'vision.extract': str(conn.id)}}}

        get_settings_mock = AsyncMock(return_value=settings)
        get_connection_mock = AsyncMock(return_value=conn)

        with (
            patch(
                'app.core.public_api.core_api.organizations.get_settings_async',
                get_settings_mock,
            ),
            patch(
                'app.core.llm.registry._get_connection',
                get_connection_mock,
            ),
        ):
            from app.core.llm.registry import get_client_for_purpose

            result = await get_client_for_purpose(
                AsyncMock(), org_id=org_id, purpose_key='vision.extract'
            )

        assert result is None
        assert get_settings_mock.await_count == 1
        assert get_connection_mock.await_count == 1
