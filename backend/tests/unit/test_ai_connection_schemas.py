"""Unit tests for app.schemas.ai_connection.

The wire-format Pydantic models for /ai-connections. The most
load-bearing contract is the *round-trip* through the MASKED_VALUE
trick on api_key:

- AiConnectionCreate accepts plaintext (newly supplied).
- AiConnectionSchema always returns MASKED_VALUE for the api_key
  field when the secret is set.
- AiConnectionUpdate accepts ``\"**********\"`` to mean \"keep the
  stored cipher\" — modelled after the existing llm.api_key field
  (see app.services.crypto_service.mask_settings).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.llm.enums import LlmCapability, LlmProvider
from app.services.crypto_service import MASKED_VALUE


class TestAiConnectionCreate:
    def test_minimal_create(self):
        from app.schemas.ai_connection import AiConnectionCreate

        conn = AiConnectionCreate(
            name='GPT-4o Vision',
            provider=LlmProvider.OPENROUTER,
            api_base_url='https://openrouter.ai/api/v1',
        )
        assert conn.name == 'GPT-4o Vision'
        # Sensible defaults
        assert conn.api_key is None  # plaintext: NULL/None means \"no key\"
        assert conn.model_name == ''
        assert conn.capabilities == []

    def test_provider_accepts_string_too(self):
        """The OpenAPI frontend sends raw strings — the schema must
        accept \"openrouter\" as well as the enum value."""
        from app.schemas.ai_connection import AiConnectionCreate

        conn = AiConnectionCreate(
            name='LLM',
            provider='openrouter',  # type: ignore[arg-type]
            api_base_url='https://openrouter.ai/api/v1',
        )
        assert conn.provider == LlmProvider.OPENROUTER

    def test_base_url_refusal_names_the_field(self):
        """The refusal's ``loc`` carries ``api_base_url`` so a caller (and
        the create form) can attach it to the input it belongs under,
        instead of parsing the field name out of the message text."""
        from app.schemas.ai_connection import AiConnectionCreate

        with pytest.raises(ValidationError) as exc_info:
            AiConnectionCreate(
                name='x',
                provider=LlmProvider.OPENROUTER,
                api_base_url='',
            )

        (error,) = exc_info.value.errors()
        assert error['loc'] == ('api_base_url',)
        assert not error['msg'].startswith('api_base_url')

    def test_invalid_provider_rejected(self):
        from app.schemas.ai_connection import AiConnectionCreate

        with pytest.raises(ValidationError):
            AiConnectionCreate(
                name='x',
                provider='bogus-provider',
            )

    def test_capabilities_must_be_recognised(self):
        from app.schemas.ai_connection import AiConnectionCreate

        with pytest.raises(ValidationError):
            AiConnectionCreate(
                name='x',
                provider=LlmProvider.OPENROUTER,
                capabilities=['bogus-capability'],  # type: ignore[list-item]
            )

    def test_capabilities_accept_known_values(self):
        from app.schemas.ai_connection import AiConnectionCreate

        conn = AiConnectionCreate(
            name='x',
            provider=LlmProvider.GOOGLE,
            capabilities=[LlmCapability.VISION, LlmCapability.TEXT],
        )
        assert LlmCapability.VISION in conn.capabilities


class TestAiConnectionUpdate:
    def test_all_fields_optional(self):
        """Update is a PATCH — every field is optional so the client
        can send only the ones that changed."""
        from app.schemas.ai_connection import AiConnectionUpdate

        u = AiConnectionUpdate(name='new name')
        assert u.name == 'new name'
        assert u.api_key is None
        assert u.model_name is None

    def test_api_key_can_be_masked_value(self):
        """``\"**********\"`` means \"keep the existing cipher\"; the
        router translates this into a no-op on the api_key_enc column."""
        from app.schemas.ai_connection import AiConnectionUpdate

        u = AiConnectionUpdate(api_key=MASKED_VALUE)  # type: ignore[arg-type]
        assert u.api_key == MASKED_VALUE

    def test_api_key_can_be_plaintext(self):
        from app.schemas.ai_connection import AiConnectionUpdate

        u = AiConnectionUpdate(api_key='sk-or-new-key')
        assert u.api_key == 'sk-or-new-key'


class TestAiConnectionSchema:
    """Read-side serializer. ``api_key\" is always MASKED_VALUE-or-empty
    — the plaintext never leaves the backend."""

    def test_api_key_masked(self):
        from app.schemas.ai_connection import AiConnectionSchema

        s = AiConnectionSchema(
            id='00000000-0000-0000-0000-000000000001',
            name='x',
            provider=LlmProvider.OPENROUTER,
            api_key=MASKED_VALUE,  # what the router hands back
            api_base_url='https://openrouter.ai/api/v1',
            model_name='m',
            temperature=None,
            max_tokens=None,
            top_p=None,
            capabilities=[],
            created_at='2026-01-01T00:00:00Z',
            updated_at='2026-01-01T00:00:00Z',
        )
        assert s.api_key == MASKED_VALUE

    def test_api_key_empty_passthrough(self):
        from app.schemas.ai_connection import AiConnectionSchema

        s = AiConnectionSchema(
            id='00000000-0000-0000-0000-000000000001',
            name='x',
            provider=LlmProvider.OPENROUTER,
            api_key='',
            api_base_url='',
            model_name='',
            temperature=None,
            max_tokens=None,
            top_p=None,
            capabilities=[],
            created_at='2026-01-01T00:00:00Z',
            updated_at='2026-01-01T00:00:00Z',
        )
        assert s.api_key == ''


class TestAiPurposeSchema:
    def test_includes_bound_connection_id(self):
        from app.schemas.ai_connection import AiPurposeSchema

        purpose = AiPurposeSchema(
            key='vision.extract',
            capability=LlmCapability.VISION,
            label_key='vision:ai.purposeLabel',
            description_key='vision:ai.purposeDesc',
            owner_module='vision',
            bound_connection_id=None,
        )
        assert purpose.key == 'vision.extract'
        assert purpose.bound_connection_id is None

    def test_bound_connection_id_can_be_set(self):
        from app.schemas.ai_connection import AiPurposeSchema

        purpose = AiPurposeSchema(
            key='vision.extract',
            capability=LlmCapability.VISION,
            label_key='l',
            description_key='d',
            owner_module='vision',
            bound_connection_id='00000000-0000-0000-0000-000000000001',
        )
        # Pydantic auto-parses the string to a UUID; the assertion
        # checks the semantic value, not the type.
        assert purpose.bound_connection_id == uuid.UUID(
            '00000000-0000-0000-0000-000000000001'
        )


class TestSetBindingRequest:
    def test_minimal_set_binding(self):
        from app.schemas.ai_connection import SetBindingRequest

        req = SetBindingRequest(
            purpose_key='vision.extract',
            connection_id='00000000-0000-0000-0000-000000000001',
        )
        assert req.purpose_key == 'vision.extract'
        # Pydantic auto-parses the string to a UUID.
        assert req.connection_id == uuid.UUID('00000000-0000-0000-0000-000000000001')


class TestAllProvidersAccepted:
    """The schema must accept every value in the widened LlmProvider enum.

    A regression here means the enum was widened but the schema's
    ``provider: LlmProvider`` annotation stopped matching (e.g. the
    OpenAPI frontend sends a string that Pydantic refuses).
    """

    def test_each_provider_parses(self):
        from app.core.llm.enums import LlmProvider
        from app.schemas.ai_connection import AiConnectionCreate

        for provider in LlmProvider:
            conn = AiConnectionCreate(
                name=f'test-{provider.value}',
                provider=provider,
                api_base_url='https://example.com/v1',
            )
            assert conn.provider == provider
