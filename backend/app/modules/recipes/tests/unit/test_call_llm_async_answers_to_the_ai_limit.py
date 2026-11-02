"""The recipes LLM entry point spends the budget, so the budget gates it.

Every recipes provider call — scraping, ingredient parsing, translation,
template matching — goes through :func:`call_llm_async`, and every one of
them books an AI-usage row against the organization's monthly ceiling. The
gate belongs at that single entry point so a new consumer cannot be added
outside it: over the limit the provider is never reached, under it the call
still runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.exceptions import TooManyRequestsException
from app.core.public_api.ai_usage import CoreAIUsageAPI
from app.i18n.service import get_error_message
from app.modules.recipes._llm_client import call_llm_async
from app.services.ai_usage_service import AIUsageLimitExceededError


def _exceeded() -> AIUsageLimitExceededError:
    return AIUsageLimitExceededError(
        'Monthly AI request limit exceeded (3/2). Contact your administrator.',
        limit_key='ai_requests_monthly',
        used=3,
        limit=2,
        period_start=datetime(2026, 9, 1, tzinfo=UTC),
        period_end=datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC),
    )


@pytest.mark.unit
class TestCallLlmAsyncAnswersToTheAiLimit:
    async def test_over_the_limit_the_provider_is_never_reached(self) -> None:
        client = AsyncMock()

        with (
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new=AsyncMock(return_value=client),
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
                new=AsyncMock(side_effect=_exceeded()),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await call_llm_async(AsyncMock(), uuid4(), 'parse this')

        assert exc_info.value.status_code == 429
        detail: Any = exc_info.value.detail
        assert detail['code'] == 'AI_USAGE_LIMIT_EXCEEDED'
        assert detail['limit_key'] == 'ai_requests_monthly'
        assert detail['used'] == 3
        assert detail['limit'] == 2
        client.complete.assert_not_awaited()

    async def test_the_refusal_is_an_app_exception_with_the_whole_body(self) -> None:
        with patch(
            'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
            new=AsyncMock(side_effect=_exceeded()),
        ):
            with pytest.raises(TooManyRequestsException) as exc_info:
                await CoreAIUsageAPI().enforce_limit_async(
                    AsyncMock(), uuid4(), 'recipe_import'
                )

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail == {
            'code': 'AI_USAGE_LIMIT_EXCEEDED',
            'lang': 'en',
            'message': get_error_message(
                'ai_usage_limit_exceeded_requests',
                'en',
                used=3,
                limit=2,
                period='2026-09-01 – 2026-09-30',
            ),
            'limit_key': 'ai_requests_monthly',
            'used': 3,
            'limit': 2,
            'period_start': '2026-09-01',
            'period_end': '2026-09-30',
        }

    async def test_under_the_limit_the_call_runs(self) -> None:
        from app.core.llm.base import LlmResponse

        client = AsyncMock()
        client.complete = AsyncMock(
            return_value=LlmResponse(content='{"ok": true}', usage={}, raw={})
        )

        with (
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new=AsyncMock(return_value=client),
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.check_limit_async',
                new=AsyncMock(),
            ),
            patch(
                'app.core.public_api.ai_usage.CoreAIUsageAPI.log_llm_usage_async',
                new=AsyncMock(),
            ),
        ):
            answer = await call_llm_async(AsyncMock(), uuid4(), 'parse this')

        assert answer == '{"ok": true}'
        client.complete.assert_awaited_once()
