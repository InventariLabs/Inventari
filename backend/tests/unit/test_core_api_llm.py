"""Unit tests for the core_api.llm facade."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.core.llm.enums import LlmCapability
from app.core.llm.errors import LlmContractError
from app.core.public_api import core_api
from app.core.public_api.llm import LlmRequest, LlmResponse


@pytest.mark.unit
class TestCoreLlmAPI:
    def test_reexports_available(self):
        """Modules build requests via facade re-exports, not app.core.llm."""
        request = LlmRequest(prompt='hello')
        assert request.prompt == 'hello'
        assert LlmResponse is not None

    def test_register_purpose_delegates_with_spec(self):
        with patch(
            'app.core.llm.purpose_registry.register_ai_purpose'
        ) as mock_register:
            core_api.llm.register_purpose(
                key='test.purpose',
                capability=LlmCapability.TEXT,
                label_key='test:label',
                description_key='test:desc',
                owner_module='test',
            )
        spec = mock_register.call_args.args[0]
        assert spec.key == 'test.purpose'
        assert spec.capability == LlmCapability.TEXT
        assert spec.owner_module == 'test'

    @pytest.mark.asyncio
    async def test_get_client_for_purpose_delegates(self):
        client = object()
        org_id = uuid4()
        db = AsyncMock()
        with patch(
            'app.core.llm.registry.get_client_for_purpose',
            new=AsyncMock(return_value=client),
        ) as mock_resolve:
            result = await core_api.llm.get_client_for_purpose_async(
                db, org_id, 'recipes.text_parse'
            )
        assert result is client
        mock_resolve.assert_awaited_once_with(db, org_id, 'recipes.text_parse')


class _Label(BaseModel):
    name: str | None = None


@pytest.mark.unit
class TestExtractFromImagesEnrichment:
    """The facade stamps the failing connection onto the contract error."""

    @pytest.mark.asyncio
    async def test_contract_error_carries_connection_and_model(self):
        class FakeClient:
            connection_name = 'Label Reader'
            model_name = 'gpt-4o-mini'

            async def complete(self, request):
                return LlmResponse(content='not json', usage={})

            async def list_models(self):
                return []

        with (
            patch.object(
                core_api.ai_usage,
                'check_limit_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                core_api.ai_usage,
                'log_llm_usage_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=FakeClient(),
            ),
        ):
            with pytest.raises(LlmContractError) as excinfo:
                await core_api.llm.extract_from_images_async(
                    db=AsyncMock(),
                    organization_id=uuid4(),
                    purpose_key='vision.extract',
                    schema=_Label,
                    instructions='Read the label.',
                    images=[b'fake'],
                    action_type='extract',
                )

        assert excinfo.value.connection_name == 'Label Reader'
        assert excinfo.value.model_name == 'gpt-4o-mini'
