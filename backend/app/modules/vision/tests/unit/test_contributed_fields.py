"""Reading one module's field group off a photograph that is not a label.

``extract_contributed_fields`` is what the nutrition-table scanner uses: the
picture is a table, not a package, so asking for a product name would be
noise. What vision supplies is the plumbing; what to look for comes from
whichever module registered a group under that key — and vision never learns
what the key means.

Parsing, retry and usage accounting are Core's and are tested there
(``tests/unit/test_llm_image_extraction.py``). What is tested here is the
lookup and the two ways it can be empty.
"""

from __future__ import annotations

import io
from contextlib import AbstractContextManager, ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import BaseModel, Field

from app.core.llm.base import LlmResponse
from app.core.public_api import core_api
from app.modules.vision.field_contributions import (
    LabelFieldContribution,
    clear_label_fields,
    register_label_fields,
)
from app.modules.vision.service import VisionService


class Facts(BaseModel):
    calories: float | None = Field(None, description='kcal per 100g')
    salt: float | None = Field(None, description='salt in grams per 100g')


def _jpeg() -> bytes:
    """A real (tiny) JPEG — this path re-compresses before sending."""
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 200, 200)).save(buf, format='JPEG')
    return buf.getvalue()


def _client(content: str) -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(
        return_value=LlmResponse(content=content, usage={}, raw={})
    )
    return client


def _quiet(client: AsyncMock | None) -> list[AbstractContextManager[Any]]:
    return [
        patch.object(
            core_api.ai_usage,
            'check_limit_async',
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            core_api.ai_usage,
            'log_usage_async',
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
            new_callable=AsyncMock,
            return_value=client,
        ),
    ]


@pytest.mark.unit
class TestExtractContributedFields:
    def setup_method(self) -> None:
        clear_label_fields()
        register_label_fields(
            LabelFieldContribution(
                module='nutrition',
                schema=Facts,
                instructions='Read the nutrition table, per 100 g.',
                context_tags=None,
            )
        )

    def teardown_method(self) -> None:
        clear_label_fields()
        from app.modules.nutrition.vision_fields import register_vision_fields

        register_vision_fields()

    @pytest.mark.asyncio
    async def test_it_asks_only_for_the_named_group(self) -> None:
        client = _client('{"calories": 250, "salt": 1.2}')

        with ExitStack() as stack:
            for patcher in _quiet(client):
                stack.enter_context(patcher)
            result = await VisionService.extract_contributed_fields(
                module='nutrition',
                image_bytes_list=[_jpeg()],
                db=AsyncMock(),
                organization_id=uuid4(),
                user_id=uuid4(),
            )

        assert result == {'calories': 250.0, 'salt': 1.2}
        prompt = client.complete.await_args.args[0].prompt
        assert 'nutrition table' in prompt
        # Nothing from the label schema goes along for the ride.
        assert '"brand"' not in prompt
        assert '"expiry_date"' not in prompt

    @pytest.mark.asyncio
    async def test_an_unregistered_module_is_a_programming_error(self) -> None:
        """Naming a module that registered nothing is a programming error.

        The endpoint hardcodes the module whose group it reads and is gated on
        that module being enabled, so the two cannot disagree in production.
        The check exists so that a typo in a future endpoint fails loudly
        instead of asking the model for an empty schema.
        """
        with ExitStack() as stack:
            for patcher in _quiet(_client('{}')):
                stack.enter_context(patcher)
            with pytest.raises(RuntimeError, match='no_such_module'):
                await VisionService.extract_contributed_fields(
                    module='no_such_module',
                    image_bytes_list=[_jpeg()],
                    db=AsyncMock(),
                    organization_id=uuid4(),
                    user_id=uuid4(),
                )


@pytest.mark.unit
class TestNutritionOwnsItsSchema:
    def test_the_real_module_registers_its_group(self) -> None:
        """the schema has an owner, and it is not vision.

        Registration happens in the nutrition module's contributions hook; this
        checks the declaration itself, so the assertion survives a test run
        that never started the app.
        """
        from app.modules.nutrition.schemas import NutritionFacts

        fields = set(NutritionFacts.model_fields)
        assert {'energy_kcal', 'salt', 'ingredients'} <= fields

        from app.modules.vision.schemas import VisionExtractResult

        assert fields.isdisjoint(set(VisionExtractResult.model_fields))
