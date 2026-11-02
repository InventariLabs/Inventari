"""``core_api.llm.extract_from_images_async`` — the Core half of image recognition.

These tests were the vision module's until the capability moved. They stay
worth having in Core for the reason they were written: the parts that are easy
to get wrong here are the parts nobody notices going wrong. A retry the
provider billed but nobody logged is a quota that drains without a trace; a
retry that dropped the images is a second call asking a blind model to try
harder.

The schema is a stand-in, not any module's — Core must be exercisable without
one, and what it does is the same whatever the fields are called.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.llm.base import LlmResponse
from app.core.llm.errors import LlmPurposeUnboundError
from app.core.public_api import core_api

_PURPOSE = 'vision.extract'


class Reading(BaseModel):
    name: str | None = Field(None, description='what the thing is called')
    brand: str | None = None


def _session() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    # The usage ledger opens its own session on the request's engine and
    # refuses anything not engine-bound — loudly, by design. The spec'd
    # mock satisfies that check while the session stays lazy: the cost
    # estimate and the inner write are patched, so the commit writes
    # nothing anywhere.
    db.bind = MagicMock(spec=AsyncEngine)
    return db


def _answering(*contents: tuple[str, dict[str, int]]) -> MagicMock:
    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            LlmResponse(content=content, usage=usage, raw={'model': 'test-model'})
            for content, usage in contents
        ]
    )
    return client


def _patched(client: MagicMock, log: AsyncMock) -> list:
    return [
        patch(
            'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch.object(
            core_api.ai_usage,
            'estimate_cost_async',
            new_callable=AsyncMock,
            return_value=(0.001, True),
        ),
        patch.object(
            core_api.ai_usage,
            'check_limit_async',
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(core_api.ai_usage, 'log_usage_async', log),
    ]


async def _extract(client: MagicMock, log: AsyncMock, **kwargs: object) -> Reading:
    from contextlib import ExitStack

    with ExitStack() as stack:
        for patcher in _patched(client, log):
            stack.enter_context(patcher)
        return await core_api.llm.extract_from_images_async(
            _session(),
            kwargs.pop('organization_id', None) or uuid4(),  # type: ignore[arg-type]
            purpose_key=_PURPOSE,
            schema=Reading,
            instructions='Read the label.',
            images=[b'not-really-a-jpeg'],
            action_type='extract_label',
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.mark.unit
class TestUsageAccounting:
    @pytest.mark.asyncio
    async def test_a_successful_call_is_billed(self) -> None:
        organization_id = uuid4()
        log = AsyncMock(return_value=None)
        client = _answering(
            (
                '{"name": "Test Product", "brand": "Test Brand"}',
                {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
            )
        )

        result = await _extract(
            client, log, organization_id=organization_id, user_id=uuid4()
        )

        assert result.name == 'Test Product'
        log.assert_awaited_once()
        assert log.await_args is not None
        kwargs = log.await_args.kwargs
        assert kwargs['organization_id'] == organization_id
        assert kwargs['total_tokens'] == 150
        assert kwargs['prompt_tokens'] == 100
        assert kwargs['completion_tokens'] == 50
        assert kwargs['action_type'] == 'extract_label'

    @pytest.mark.asyncio
    async def test_a_rejected_answer_is_billed_too(self) -> None:
        """The provider charges for an answer whether or not it was usable."""
        log = AsyncMock(return_value=None)
        client = _answering(
            ('I can see a carton but the text is unclear.', {'total_tokens': 40}),
            ('{"name": "Test Product"}', {'total_tokens': 60}),
        )

        result = await _extract(client, log, user_id=uuid4())

        assert result.name == 'Test Product'
        assert client.complete.await_count == 2
        assert log.await_count == 2


@pytest.mark.unit
class TestRetry:
    @pytest.mark.asyncio
    async def test_the_retry_carries_the_rejected_answer_and_the_images(self) -> None:
        log = AsyncMock(return_value=None)
        client = _answering(
            ('The label is in Hungarian.', {}),
            ('{"name": "Tej"}', {}),
        )

        await _extract(client, log, user_id=uuid4())

        first, retry = (call.args[0] for call in client.complete.await_args_list)
        assert 'The label is in Hungarian.' in retry.prompt
        assert retry.images == first.images


@pytest.mark.unit
class TestConfigurationGap:
    @pytest.mark.asyncio
    async def test_no_bound_connection_names_the_purpose(self) -> None:
        """A missing binding is somebody's unfinished setup, not an outage."""
        with (
            patch(
                'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                core_api.ai_usage,
                'check_limit_async',
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(LlmPurposeUnboundError) as exc,
        ):
            await core_api.llm.extract_from_images_async(
                _session(),
                uuid4(),
                purpose_key=_PURPOSE,
                schema=Reading,
                instructions='Read the label.',
                images=[b'not-really-a-jpeg'],
                action_type='extract_label',
            )

        assert exc.value.purpose_key == _PURPOSE


@pytest.mark.unit
class TestPromptShape:
    @pytest.mark.asyncio
    async def test_the_schema_is_what_the_model_is_asked_for(self) -> None:
        """Field names and descriptions reach the prompt from the model itself.

        The two used to be separate lists — a hand-written JSON block in the
        prompt and a Pydantic class — and drifted apart field by field.
        """
        log = AsyncMock(return_value=None)
        client = _answering(('{"name": "Tej"}', {}))

        await _extract(client, log, user_id=uuid4())

        prompt = client.complete.await_args_list[0].args[0].prompt
        assert 'Read the label.' in prompt
        assert '"name"' in prompt
        assert 'what the thing is called' in prompt


@pytest.mark.unit
class TestTheBudgetTheCallIsGiven:
    """Reading two photographs is not a text-sized task.

    A reasoning model bills its chain-of-thought as completion tokens, so a
    fixed budget spent thinking leaves nothing for the answer: the unclosed
    ``<think>`` block is stripped and what arrives is the empty string. The
    module that had met this before solved it locally; the Core path every
    other module goes through did neither half.
    """

    @pytest.mark.asyncio
    async def test_reasoning_is_switched_off(self) -> None:
        log = AsyncMock(return_value=None)
        client = _answering(('{"name": "Tej"}', {}))

        await _extract(client, log, user_id=uuid4())

        request = client.complete.await_args_list[0].args[0]
        assert request.disable_reasoning is True

    @pytest.mark.asyncio
    async def test_the_token_budget_fits_the_task(self) -> None:
        log = AsyncMock(return_value=None)
        client = _answering(('{"name": "Tej"}', {}))

        await _extract(client, log, user_id=uuid4())

        request = client.complete.await_args_list[0].args[0]
        assert request.max_tokens >= 8000

    @pytest.mark.asyncio
    async def test_a_caller_can_still_ask_for_less(self) -> None:
        log = AsyncMock(return_value=None)
        client = _answering(('{"name": "Tej"}', {}))

        await _extract(client, log, user_id=uuid4(), max_tokens=1234)

        request = client.complete.await_args_list[0].args[0]
        assert request.max_tokens == 1234


@pytest.mark.unit
class TestTheModelAnsweredWithNothing:
    @pytest.mark.asyncio
    async def test_the_provider_is_asked_exactly_once(self) -> None:
        """Twenty seconds and a second bill bought the same silence."""
        from app.core.llm.errors import LlmEmptyAnswerError

        log = AsyncMock(return_value=None)
        client = _answering(('', {'total_tokens': 2000}), ('{"name": "Tej"}', {}))

        with pytest.raises(LlmEmptyAnswerError):
            await _extract(client, log, user_id=uuid4())

        assert client.complete.await_count == 1

    @pytest.mark.asyncio
    async def test_the_failure_names_the_connection_that_answered(self) -> None:
        from app.core.llm.errors import LlmEmptyAnswerError

        log = AsyncMock(return_value=None)
        client = _answering(('', {}))
        client.connection_name = 'label reader'
        client.model_name = 'some-vision-model'

        with pytest.raises(LlmEmptyAnswerError) as caught:
            await _extract(client, log, user_id=uuid4())

        assert caught.value.connection_name == 'label reader'
        assert caught.value.model_name == 'some-vision-model'
