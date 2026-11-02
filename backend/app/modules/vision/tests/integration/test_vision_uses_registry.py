"""The vision service reaches its model through the registry, and only there.

Guards the invariant that there is no fallback to a direct-HTTP client — and,
since the extraction capability moved to Core, the invariant that replaced the
storage-type prompt: which modules' fields ride along is decided by the label's
intent, not by a default.
"""

import base64
from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from app.core.llm.base import LlmResponse
from app.core.public_api import core_api
from app.modules.vision.field_contributions import (
    PRODUCT_CONTEXT,
    LabelFieldContribution,
    clear_label_fields,
    register_label_fields,
)
from app.modules.vision.schemas import VisionExtractResponse
from app.modules.vision.service import VisionService


class Facts(BaseModel):
    """A stand-in for a module's contributed group."""

    calories: float | None = Field(None, description='kcal per 100g')


def _answering(content: str) -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(
        return_value=LlmResponse(
            content=content,
            usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
            raw={'model': 'test-model'},
        )
    )
    return client


def _quiet_usage() -> list[AbstractContextManager[Any]]:
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
        patch.object(
            core_api.ai_usage,
            'estimate_cost_async',
            new_callable=AsyncMock,
            return_value=(0.0, True),
        ),
    ]


async def _extract(
    client: AsyncMock,
    *,
    context_tag: str | None = None,
    modules_enabled: bool = True,
    extra_patches: list[AbstractContextManager[Any]] | None = None,
    disable_reasoning: bool = True,
) -> VisionExtractResponse:
    from contextlib import ExitStack

    with ExitStack() as stack:
        for patcher in [
            *_quiet_usage(),
            patch.object(
                core_api.organizations,
                'is_module_enabled_async',
                new_callable=AsyncMock,
                return_value=modules_enabled,
            ),
            *(extra_patches or []),
        ]:
            stack.enter_context(patcher)
        stack.enter_context(
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=client,
            )
        )
        return await VisionService.extract_from_base64_list(
            images_base64=[base64.b64encode(b'fake').decode()],
            db=AsyncMock(),
            organization_id=uuid4(),
            user_id=uuid4(),
            context_tag=context_tag,
            disable_reasoning=disable_reasoning,
        )


async def _extract_as_user(client: AsyncMock) -> VisionExtractResponse:
    """Extraction with a user context, which is what turns resolving on."""
    from contextlib import ExitStack

    from app.core.contracts import UserContextDTO

    user = UserContextDTO(
        id=uuid4(),
        email='scanner@example.com',
        organization_id=uuid4(),
        role='user',
    )
    with ExitStack() as stack:
        for patcher in [
            *_quiet_usage(),
            patch.object(
                core_api.organizations,
                'is_module_enabled_async',
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=client,
            ),
        ]:
            stack.enter_context(patcher)
        return await VisionService.extract_from_bytes_list(
            image_bytes_list=[b'fake'],
            db=AsyncMock(),
            organization_id=user.organization_id or uuid4(),
            user_id=user.id,
            user=user,
        )


@pytest.mark.integration
class TestVisionUsesRegistry:
    @pytest.mark.asyncio
    async def test_extract_uses_get_client_for_purpose(self) -> None:
        client = _answering('{"name": "Milk", "brand": "Milko"}')

        with patch(
            'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
            new_callable=AsyncMock,
            return_value=client,
        ) as mock_get:
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in [
                    *_quiet_usage(),
                    patch.object(
                        core_api.organizations,
                        'is_module_enabled_async',
                        new_callable=AsyncMock,
                        return_value=False,
                    ),
                ]:
                    stack.enter_context(patcher)
                result = await VisionService.extract_from_base64_list(
                    images_base64=[base64.b64encode(b'fake').decode()],
                    db=AsyncMock(),
                    organization_id=uuid4(),
                    user_id=uuid4(),
                )

        mock_get.assert_awaited_once()
        assert mock_get.await_args is not None
        args, kwargs = mock_get.await_args.args, mock_get.await_args.kwargs
        purpose_key = args[2] if len(args) >= 3 else kwargs.get('purpose_key')
        assert purpose_key == 'vision.extract'
        assert result.name == 'Milk'
        assert result.brand == 'Milko'

    @pytest.mark.asyncio
    async def test_extract_passes_low_temperature_for_precise_json(self) -> None:
        """The provider default (1.0) rewrites values it should read verbatim."""
        client = _answering('{}')

        await _extract(client, modules_enabled=False)

        request = client.complete.await_args.args[0]
        assert request.temperature == 0.2
        # Two photographs and a schema several modules contributed to. The old
        # 2000 was a text-sized budget, and on a reasoning model it was spent
        # on chain-of-thought before the answer began.
        assert request.max_tokens >= 8000
        assert request.disable_reasoning is True

    @pytest.mark.asyncio
    async def test_the_chain_of_thought_switch_is_a_default_not_a_constant(
        self,
    ) -> None:
        """Off by default, and off because a caller may ask for it on.

        The value was chosen from one log line on one model whose budget was
        2000 tokens; the budget is 8000 now. Reading a label is also not pure
        transcription — deciding whether a figure on a wrapper is the net
        weight or a per-serving reference is a judgement. Whether skipping
        the chain of thought helps or hurts is therefore a measurement, and a
        constant is a value no measurement can reach.
        """
        client = _answering('{}')

        await _extract(client, modules_enabled=False, disable_reasoning=False)

        request = client.complete.await_args.args[0]
        assert request.disable_reasoning is False

    @pytest.mark.asyncio
    async def test_extract_raises_when_no_binding(self) -> None:
        """No bound client → a named configuration error, no default model."""
        from contextlib import ExitStack

        from app.core.llm.errors import LlmPurposeUnboundError

        with ExitStack() as stack:
            for patcher in [
                *_quiet_usage(),
                patch(
                    'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                    new_callable=AsyncMock,
                    return_value=None,
                ),
            ]:
                stack.enter_context(patcher)
            with pytest.raises(LlmPurposeUnboundError):
                await VisionService.extract_from_base64_list(
                    images_base64=[base64.b64encode(b'fake').decode()],
                    db=AsyncMock(),
                    organization_id=uuid4(),
                    user_id=uuid4(),
                )


@pytest.mark.integration
class TestContributedFieldsFollowIntent:
    """the prompt for a rating plate does not mention food."""

    def setup_method(self) -> None:
        clear_label_fields()
        register_label_fields(
            LabelFieldContribution(
                module='nutrition',
                schema=Facts,
                instructions='Only when a nutrition table is legible.',
                context_tags=frozenset({PRODUCT_CONTEXT}),
            )
        )

    def teardown_method(self) -> None:
        clear_label_fields()
        # Restore the real registrations the app made at import time.
        from app.modules.nutrition.vision_fields import register_vision_fields

        register_vision_fields()

    @pytest.mark.asyncio
    async def test_a_product_label_carries_the_contributed_group(self) -> None:
        client = _answering('{"name": "Milk", "nutrition": {"calories": 42}}')

        result = await _extract(client, context_tag=None)

        prompt = client.complete.await_args.args[0].prompt
        assert 'nutrition table' in prompt
        assert result.extra['nutrition']['calories'] == 42

    @pytest.mark.asyncio
    async def test_an_asset_label_is_never_asked_about_nutrition(self) -> None:
        client = _answering('{"name": "ThinkPad T14"}')

        result = await _extract(client, context_tag='equipment')

        prompt = client.complete.await_args.args[0].prompt
        assert 'nutrition' not in prompt.lower()
        assert 'calories' not in prompt.lower()
        assert result.extra == {}

    @pytest.mark.asyncio
    async def test_a_disabled_module_contributes_nothing(self) -> None:
        client = _answering('{"name": "Milk"}')

        result = await _extract(client, context_tag=None, modules_enabled=False)

        assert 'nutrition' not in client.complete.await_args.args[0].prompt.lower()
        assert result.extra == {}


@pytest.mark.integration
class TestBarcodeGoesThroughTheResolvers:
    """a barcode read off a photograph is resolved like a scanned one."""

    @pytest.mark.asyncio
    async def test_a_legible_barcode_is_handed_to_the_scan_chain(self) -> None:
        from app.schemas.label_pool import LabelScanResponse

        client = _answering('{"name": "Milk", "barcode": "5901234123457"}')
        resolved = LabelScanResponse(
            status='unassigned',
            label_code='5901234123457',
            message='Mleko 2%',
            action='show_quick_add',
            stock_summary={
                'template': {'name': 'Mleko 2%', 'brand': 'Mlekovita'},
                'total_quantity': 0,
                'items': [],
            },
        )

        with patch(
            'app.modules.vision.service.scan_registry.scan',
            new_callable=AsyncMock,
            return_value=resolved,
        ) as scan:
            result = await _extract_as_user(client)

        scan.assert_awaited_once()
        assert scan.await_args is not None
        assert scan.await_args.args[0] == '5901234123457'
        assert result.resolved == {'name': 'Mleko 2%', 'brand': 'Mlekovita'}

    @pytest.mark.asyncio
    async def test_no_barcode_means_no_lookup(self) -> None:
        client = _answering('{"name": "Home-made jam"}')

        with patch(
            'app.modules.vision.service.scan_registry.scan',
            new_callable=AsyncMock,
        ) as scan:
            result = await _extract_as_user(client)

        scan.assert_not_awaited()
        assert result.resolved is None

    @pytest.mark.asyncio
    async def test_a_failing_resolver_still_returns_what_was_read(self) -> None:
        """Enrichment that can block a reading is worse than no enrichment."""
        client = _answering('{"name": "Milk", "barcode": "5901234123457"}')

        with patch(
            'app.modules.vision.service.scan_registry.scan',
            new_callable=AsyncMock,
            side_effect=OSError('product database unavailable'),
        ):
            result = await _extract_as_user(client)

        assert result.name == 'Milk'
        assert result.resolved is None
