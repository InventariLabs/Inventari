"""Unit tests for ``complete_json`` — one retry with the error fed back.

The client is a structural stand-in for the ``LlmClient`` protocol: no httpx,
no registry, no network. What is under test is the decision of when to ask
again and what to say when asking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.core.llm.base import LlmRequest, LlmResponse
from app.core.llm.errors import LlmContractError, LlmEmptyAnswerError
from app.core.llm.json_parsing import extract_json_object
from app.core.llm.json_retry import complete_json, default_retry_prompt


@dataclass
class FakeClient:
    """Structural ``LlmClient``: hands back canned answers, in order."""

    answers: list[str | Exception]
    finish_reason: str | None = None
    seen: list[LlmRequest] = field(default_factory=list)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.seen.append(request)
        answer = self.answers[len(self.seen) - 1]
        if isinstance(answer, Exception):
            raise answer
        return LlmResponse(
            content=answer,
            usage={'total_tokens': 10},
            finish_reason=self.finish_reason,
        )


def _request(prompt: str = 'Read the label.') -> LlmRequest:
    return LlmRequest(prompt=prompt, temperature=0.2)


@pytest.mark.unit
class TestFirstAttemptSucceeds:
    async def test_returns_value_and_response(self) -> None:
        client = FakeClient(['{"name": "Milk"}'])
        value, response = await complete_json(
            client, _request(), validate=extract_json_object
        )
        assert value == {'name': 'Milk'}
        assert response.usage == {'total_tokens': 10}

    async def test_client_is_called_exactly_once(self) -> None:
        client = FakeClient(['{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 1

    async def test_prompt_is_sent_unchanged(self) -> None:
        client = FakeClient(['{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert client.seen[0].prompt == 'Read the label.'


@pytest.mark.unit
class TestRetry:
    async def test_second_attempt_wins(self) -> None:
        client = FakeClient(['I cannot read this.', '{"name": "Milk"}'])
        value, _ = await complete_json(client, _request(), validate=extract_json_object)
        assert value == {'name': 'Milk'}
        assert len(client.seen) == 2

    async def test_retry_prompt_quotes_the_previous_answer(self) -> None:
        client = FakeClient(['I cannot read this.', '{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert 'I cannot read this.' in client.seen[1].prompt

    async def test_retry_prompt_states_the_problem(self) -> None:
        def validate(content: str) -> Any:
            raise LlmContractError("weight_value='about 500 g' is not a number")

        client = FakeClient(['{"weight_value": "about 500 g"}', '{"a": 1}'])
        with pytest.raises(LlmContractError):
            await complete_json(client, _request(), validate=validate)
        assert 'about 500 g' in client.seen[1].prompt

    async def test_retry_prompt_keeps_the_original_instruction(self) -> None:
        client = FakeClient(['nope', '{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert client.seen[1].prompt.startswith('Read the label.')

    async def test_original_request_is_not_mutated(self) -> None:
        request = _request()
        client = FakeClient(['nope', '{"name": "Milk"}'])
        await complete_json(client, request, validate=extract_json_object)
        assert request.prompt == 'Read the label.'

    async def test_sampling_settings_survive_the_retry(self) -> None:
        client = FakeClient(['nope', '{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert client.seen[1].temperature == 0.2

    async def test_a_long_previous_answer_is_truncated(self) -> None:
        client = FakeClient(['x' * 5000, '{"name": "Milk"}'])
        await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen[1].prompt) < 2000


@pytest.mark.unit
class TestBothAttemptsFail:
    async def test_the_last_error_propagates(self) -> None:
        client = FakeClient(['nope', 'still nope'])
        with pytest.raises(json.JSONDecodeError):
            await complete_json(client, _request(), validate=extract_json_object)

    async def test_the_client_is_called_exactly_twice(self) -> None:
        client = FakeClient(['nope', 'still nope'])
        with pytest.raises(json.JSONDecodeError):
            await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 2

    async def test_max_attempts_one_means_no_retry(self) -> None:
        client = FakeClient(['nope', '{"name": "Milk"}'])
        with pytest.raises(json.JSONDecodeError):
            await complete_json(
                client, _request(), validate=extract_json_object, max_attempts=1
            )
        assert len(client.seen) == 1


@pytest.mark.unit
class TestTransportFailuresAreNotRetried:
    """A dead provider is not a model that misunderstood the question."""

    async def test_http_error_propagates_on_the_first_attempt(self) -> None:
        client = FakeClient([httpx.ConnectError('provider unreachable')])
        with pytest.raises(httpx.ConnectError):
            await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 1

    async def test_runtime_error_from_the_client_propagates(self) -> None:
        client = FakeClient([RuntimeError('no connection bound')])
        with pytest.raises(RuntimeError, match='no connection bound'):
            await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 1


@pytest.mark.unit
class TestAnEmptyAnswerIsNotRetried:
    """No answer is not an answer of the wrong shape.

    Asking again cost twenty seconds and a second bill for the same silence,
    and the retry prompt handed the model back its own empty string as the
    mistake to correct.
    """

    async def test_the_client_is_called_exactly_once(self) -> None:
        client = FakeClient(['', '{"name": "Milk"}'])
        with pytest.raises(LlmEmptyAnswerError):
            await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 1

    async def test_whitespace_counts_as_empty(self) -> None:
        client = FakeClient(['   \n  ', '{"name": "Milk"}'])
        with pytest.raises(LlmEmptyAnswerError):
            await complete_json(client, _request(), validate=extract_json_object)
        assert len(client.seen) == 1

    async def test_it_is_still_a_contract_error(self) -> None:
        """Routers that answer for an unusable answer keep answering."""
        client = FakeClient([''])
        with pytest.raises(LlmContractError):
            await complete_json(client, _request(), validate=extract_json_object)

    async def test_the_message_carries_the_provider_reason(self) -> None:
        client = FakeClient([''], finish_reason='length')
        with pytest.raises(LlmEmptyAnswerError) as caught:
            await complete_json(client, _request(), validate=extract_json_object)
        assert caught.value.finish_reason == 'length'
        assert 'token limit' in str(caught.value)

    async def test_the_attempt_is_still_billed(self) -> None:
        """It cost tokens whether or not anything came back."""
        logged: list[LlmResponse] = []

        async def record(response: LlmResponse) -> None:
            logged.append(response)

        client = FakeClient([''])
        with pytest.raises(LlmEmptyAnswerError):
            await complete_json(
                client, _request(), validate=extract_json_object, on_response=record
            )
        assert len(logged) == 1


@pytest.mark.unit
class TestUsageAccounting:
    async def test_every_attempt_is_reported(self) -> None:
        """A retry costs tokens; both attempts have to reach the usage log."""
        logged: list[LlmResponse] = []

        async def record(response: LlmResponse) -> None:
            logged.append(response)

        client = FakeClient(['nope', '{"name": "Milk"}'])
        await complete_json(
            client, _request(), validate=extract_json_object, on_response=record
        )
        assert len(logged) == 2

    async def test_reported_even_when_both_attempts_fail(self) -> None:
        logged: list[LlmResponse] = []

        async def record(response: LlmResponse) -> None:
            logged.append(response)

        client = FakeClient(['nope', 'still nope'])
        with pytest.raises(json.JSONDecodeError):
            await complete_json(
                client, _request(), validate=extract_json_object, on_response=record
            )
        assert len(logged) == 2


@pytest.mark.unit
class TestCustomRetryPrompt:
    async def test_caller_can_replace_the_wording(self) -> None:
        def build(request: LlmRequest, previous: str, error: Exception) -> LlmRequest:
            return LlmRequest(prompt='Try again, briefly.')

        client = FakeClient(['nope', '{"name": "Milk"}'])
        await complete_json(
            client,
            _request(),
            validate=extract_json_object,
            build_retry_prompt=build,
        )
        assert client.seen[1].prompt == 'Try again, briefly.'


@pytest.mark.unit
class TestDefaultRetryPrompt:
    def test_names_both_the_answer_and_the_problem(self) -> None:
        request = _request()
        retry = default_retry_prompt(request, 'garbage', ValueError('bad shape'))
        assert 'garbage' in retry.prompt
        assert 'bad shape' in retry.prompt

    def test_carries_the_images_over(self) -> None:
        request = LlmRequest(prompt='Read it.', images=[b'jpeg-bytes'])
        retry = default_retry_prompt(request, 'garbage', ValueError('bad'))
        assert retry.images == [b'jpeg-bytes']
