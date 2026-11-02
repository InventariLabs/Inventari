"""What the LLM layer does when the call does not go well.

Three failures that used to look alike from the outside and are nothing alike
to whoever is waiting:

* the provider was never reached — a refused connection, a timeout, a
  certificate the client would not accept. ``httpx`` reports these with types
  that inherit from neither ``OSError`` nor anything a router catches, so an
  unreachable endpoint left image recognition as a bare HTTP 500 in 1.3
  seconds, before the model had been asked anything.
* the provider answered with nothing. The usual cause is a reasoning model
  spending its whole token budget on chain-of-thought, whose unclosed block is
  then stripped to the empty string.
* the provider answered with something unusable, which is the only one of the
  three worth asking about a second time.

The HTTP layer is ``httpx.MockTransport`` — no network, no registry.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.core.llm.base import LlmRequest
from app.core.llm.errors import LlmProviderRefusalError, LlmTransportError
from app.core.llm.openai_client import OpenAiCompatibleClient

pytestmark = pytest.mark.unit


def _connection(provider: str = 'openrouter'):
    from app.models.ai_connection import AiConnection

    return AiConnection(
        organization_id=uuid.UUID('00000000-0000-0000-0000-000000000001'),
        name='label reader',
        provider=provider,
        api_key_enc='sk-test',
        api_base_url='https://openrouter.ai/api/v1',
        model_name='deepseek-v4-flash-vision-exp',
        capabilities=['vision', 'text'],
    )


def _client(handler, provider: str = 'openrouter') -> OpenAiCompatibleClient:
    return OpenAiCompatibleClient(
        _connection(provider), _transport=httpx.MockTransport(handler)
    )


def _refusing(exc: type[httpx.HTTPError]):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc('the provider was not reachable', request=request)

    return handler


def _refused(status_code: int, body: str = '{"error": "invalid api key"}'):
    """A provider that answered, refusing the request itself."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    return handler


def _answering(content: str, finish_reason: str | None = None, **usage: int):
    choice: dict = {'message': {'content': content}}
    if finish_reason is not None:
        choice['finish_reason'] = finish_reason

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'choices': [choice], 'usage': usage})

    return handler


class TestTheProviderWasNeverReached:
    async def test_a_refused_connection_is_named_as_transport(self) -> None:
        client = _client(_refusing(httpx.ConnectError))
        with pytest.raises(LlmTransportError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        # The kind of failure, because a timeout and a refused connection send
        # an administrator to two different places.
        assert 'ConnectError' in str(caught.value)

    async def test_a_timeout_is_named_as_transport(self) -> None:
        client = _client(_refusing(httpx.ReadTimeout))
        with pytest.raises(LlmTransportError, match='ReadTimeout'):
            await client.complete(LlmRequest(prompt='Read the label.'))

    async def test_it_carries_the_connection_that_could_not_be_reached(
        self,
    ) -> None:
        client = _client(_refusing(httpx.ConnectError))
        with pytest.raises(LlmTransportError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caught.value.connection_name == 'label reader'
        assert caught.value.model_name == 'deepseek-v4-flash-vision-exp'

    async def test_listing_models_fails_the_same_way(self) -> None:
        """The connection test walks this path, and reports on it."""
        client = _client(_refusing(httpx.ConnectError))
        with pytest.raises(LlmTransportError):
            await client.list_models()

    async def test_it_is_a_runtime_error(self) -> None:
        """Call sites that already degrade on ``RuntimeError`` keep degrading
        rather than having to learn a new type."""
        client = _client(_refusing(httpx.ConnectError))
        with pytest.raises(RuntimeError):
            await client.complete(LlmRequest(prompt='Read the label.'))


class TestTheProviderRefusedTheRequest:
    """The provider answered and said no about the request itself.

    A 401 is not an outage: it is the most common first-setup state — a key
    pasted with a typo, an expired key, a key for another project. The
    administrator who just pasted it must be told the key is the matter, not
    that the application broke. 402/429 and 404 are the same kind of answer:
    the provider read us fine and refused the key, the budget, or the model
    name, all of which are settings a person can fix.
    """

    async def test_a_rejected_key_is_its_own_failure(self) -> None:
        client = _client(_refused(401))
        with pytest.raises(LlmProviderRefusalError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caught.value.status_code == 401

    async def test_a_spent_limit_is_the_same_kind(self) -> None:
        client = _client(_refused(429))
        with pytest.raises(LlmProviderRefusalError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caught.value.status_code == 429

    async def test_an_unknown_model_is_the_same_kind(self) -> None:
        client = _client(_refused(404))
        with pytest.raises(LlmProviderRefusalError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caught.value.status_code == 404

    async def test_it_carries_the_connection_and_the_model(self) -> None:
        client = _client(_refused(401))
        with pytest.raises(LlmProviderRefusalError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caught.value.connection_name == 'label reader'
        assert caught.value.model_name == 'deepseek-v4-flash-vision-exp'

    async def test_a_provider_fault_stays_a_plain_runtime_error(self) -> None:
        """A 500 from the provider is our outage, not a setting: no
        administrator action exists for it, so it must not borrow the named
        sentences the actionable refusals carry."""
        client = _client(_refused(500))
        with pytest.raises(RuntimeError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert not isinstance(caught.value, LlmProviderRefusalError)

    async def test_listing_models_classifies_the_same_way(self) -> None:
        """The connection test walks this path, and its verdict about the
        pasted key is the first thing an administrator sees."""
        client = _client(_refused(401))
        with pytest.raises(LlmProviderRefusalError) as caught:
            await client.list_models()
        assert caught.value.status_code == 401

    async def test_it_is_still_a_runtime_error(self) -> None:
        """Call sites that already degrade on ``RuntimeError`` keep
        degrading rather than having to learn a new type."""
        client = _client(_refused(401))
        with pytest.raises(RuntimeError):
            await client.complete(LlmRequest(prompt='Read the label.'))


class TestWhyTheModelStopped:
    async def test_the_provider_reason_travels_on_the_response(self) -> None:
        client = _client(_answering('{"a": 1}', finish_reason='length'))
        response = await client.complete(LlmRequest(prompt='Read the label.'))
        assert response.finish_reason == 'length'

    async def test_a_provider_that_says_nothing_leaves_it_unset(self) -> None:
        client = _client(_answering('ok'))
        response = await client.complete(LlmRequest(prompt='Read the label.'))
        assert response.finish_reason is None

    async def test_the_warning_carries_the_three_numbers(self, caplog) -> None:
        """The log line used to read ``Answer began: ''`` — a report on what
        had just been cut out, silent about what arrived."""
        client = _client(
            _answering(
                '<think>still thinking', finish_reason='length', completion_tokens=2000
            )
        )
        with caplog.at_level('WARNING'):
            response = await client.complete(LlmRequest(prompt='Read the label.'))

        assert response.content == ''
        assert "finish_reason='length'" in caplog.text
        assert 'completion_tokens' in caplog.text
        # The length of what came in, not of what survived stripping.
        assert 'raw_length=21' in caplog.text

    async def test_a_good_answer_is_not_warned_about(self, caplog) -> None:
        client = _client(_answering('{"a": 1}', finish_reason='stop'))
        with caplog.at_level('WARNING'):
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert caplog.text == ''

    async def test_the_full_answer_is_debug_only(self, caplog) -> None:
        """A model's answer can carry whatever was printed on the document it
        just read, so the whole of it belongs to a level nobody runs by
        default."""
        client = _client(_answering('SECRET INVOICE TEXT', finish_reason='stop'))

        with caplog.at_level('WARNING'):
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert 'SECRET INVOICE TEXT' not in caplog.text

        caplog.clear()
        with caplog.at_level('DEBUG'):
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert 'SECRET INVOICE TEXT' in caplog.text


class TestAModelThatCannotStopThinking:
    """Not every endpoint has a switch, and not every endpoint ignores one.

    Three ways this goes. The provider honours the key; the provider has never
    heard of it and ignores it; the provider has never heard of it and answers
    400. Only the third could break the call, and it is the one that appeared
    the moment the image path started sending the key at all.
    """

    def _refusing_then_answering(self, key: str, calls: list[dict]):
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            body = _json.loads(request.content.decode())
            calls.append(body)
            if key in body:
                return httpx.Response(
                    400,
                    json={'error': {'message': f'Unknown parameter: {key}'}},
                )
            return httpx.Response(
                200,
                json={
                    'choices': [
                        {'message': {'content': '{"a": 1}'}, 'finish_reason': 'stop'}
                    ],
                    'usage': {},
                },
            )

        return handler

    async def test_a_refused_thinking_switch_does_not_lose_the_answer(self) -> None:
        # `thinking` is the spelling everything outside OpenRouter gets.
        calls: list[dict] = []
        client = _client(self._refusing_then_answering('thinking', calls), 'custom')

        response = await client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )

        assert response.content == '{"a": 1}'
        assert len(calls) == 2
        assert 'thinking' in calls[0]
        assert 'thinking' not in calls[1]

    async def test_a_refused_reasoning_switch_is_dropped_too(self) -> None:
        """OpenRouter's spelling of the same key."""
        calls: list[dict] = []
        client = _client(self._refusing_then_answering('reasoning', calls))

        response = await client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )

        assert response.content == '{"a": 1}'
        assert 'reasoning' not in calls[1]

    async def test_a_400_about_something_else_is_not_papered_over(self) -> None:
        """Retrying on every 400 would hide a genuinely malformed request."""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(400, json={'error': {'message': 'model not found'}})

        client = _client(handler)
        with pytest.raises(RuntimeError, match='400'):
            await client.complete(
                LlmRequest(prompt='Read the label.', disable_reasoning=True)
            )
        assert len(calls) == 1

    async def test_the_answer_still_says_why_it_ran_out(self) -> None:
        """Where the switch cannot be had at all, the budget is the defence and
        the reason is what turns "unreadable label" into "out of tokens"."""
        client = _client(_answering('', finish_reason='length'))

        response = await client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )

        assert response.content == ''
        assert response.finish_reason == 'length'


class TestARefusalIsRememberedNotRepaid:
    """A provider that refused an optional key once gets the key dropped
    from the start on the next calls — for a bounded hour, because
    OpenRouter's model id is a pool of hosts that do not agree, and a
    route that changed its mind must be re-learned, not concluded."""

    @pytest.fixture(autouse=True)
    def _clean_memory(self):
        from app.core.llm import _optional_payload

        _optional_payload._refused_since.clear()
        yield
        _optional_payload._refused_since.clear()

    @staticmethod
    def _refusing_then_answering(key: str, calls: list):
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            body = _json.loads(request.content)
            calls.append(body)
            if key in body:
                return httpx.Response(
                    400,
                    json={
                        'error': {
                            'message': f'Unknown parameter: {key}',
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    'choices': [{'message': {'content': '{"a": 1}'}}],
                    'usage': {},
                },
            )

        return handler

    async def test_the_next_call_does_not_pay_for_the_refusal_again(self) -> None:
        from app.core.llm._optional_payload import remembered_rejections

        calls: list[dict] = []
        conn = _connection()
        conn.id = uuid.uuid4()  # the same row every resolution resolves to
        client = OpenAiCompatibleClient(
            conn,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )

        await client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert len(calls) == 2  # refused once, retried without the key
        assert 'reasoning' in calls[0]
        assert 'reasoning' not in calls[1]

        # A fresh client for the same connection (the factory builds one per
        # resolution) does not send the key at all — and is not refused.
        calls.clear()
        fresh = OpenAiCompatibleClient(
            conn,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )
        response = await fresh.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert response.content == '{"a": 1}'
        assert len(calls) == 1
        assert 'reasoning' not in calls[0]
        assert remembered_rejections(conn) == frozenset({'reasoning'})

    async def test_a_draft_of_another_route_still_asks_the_question(
        self, stub_dns
    ) -> None:
        """Two unsaved drafts (the pre-save "test connection" probe), same
        provider, same base URL, different organizations: the second
        organization must ask the question itself — a route's refusal is
        not every organization's refusal. The connection form fills the
        same default base URL in for everyone, so the address alone does
        not separate drafts; the organization does."""
        from app.core.llm._optional_payload import remembered_rejections

        calls: list[dict] = []
        first = _client(self._refusing_then_answering('reasoning', calls))
        await first.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert len(calls) == 2  # refused once, retried without the key
        assert remembered_rejections(_connection()) == frozenset({'reasoning'})

        calls.clear()
        other = _connection()
        other.organization_id = uuid.UUID(
            '00000000-0000-0000-0000-000000000002'
        )  # another organization, same provider default
        other_client = OpenAiCompatibleClient(
            other,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )
        await other_client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert len(calls) == 2  # asked on its own merits, refusal not inherited
        assert 'reasoning' in calls[0]

    async def test_another_connection_still_sends_the_key(self) -> None:
        from app.core.llm._optional_payload import remembered_rejections

        calls: list[dict] = []
        first_conn = _connection()
        first_conn.id = uuid.uuid4()
        first = OpenAiCompatibleClient(
            first_conn,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )
        await first.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert remembered_rejections(first_conn) == frozenset({'reasoning'})
        calls.clear()

        other = _connection()
        other.id = uuid.uuid4()  # a different row, a different route history
        other_client = OpenAiCompatibleClient(
            other,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )
        await other_client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert len(calls) == 2  # refused on its own merits, not inherited
        assert 'reasoning' in calls[0]

    async def test_a_changed_model_still_asks_the_question(self) -> None:
        """The refusal is the model's, and a saved row is where a model gets
        changed: the connection that goes from a model which refused the key
        to another must ask on the model's own merits, not wait out the
        previous model's hour."""
        from app.core.llm._optional_payload import remembered_rejections

        row_id = uuid.uuid4()
        calls: list[dict] = []
        refused = _connection()
        refused.id = row_id
        await OpenAiCompatibleClient(
            refused,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))
        assert len(calls) == 2  # refused once, retried without the key
        assert remembered_rejections(refused) == frozenset({'reasoning'})
        calls.clear()

        switched = _connection()  # the same saved row, naming another model
        switched.id = row_id
        switched.model_name = 'deepseek-v4-flash'
        response = await OpenAiCompatibleClient(
            switched,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))

        assert response.content == '{"a": 1}'
        assert len(calls) == 2  # asked, refused, retried: its own hour starts
        assert 'reasoning' in calls[0]

    async def test_the_switched_model_still_gets_the_key(self) -> None:
        """What the user sees: the model that does support the key receives
        it on the first request, instead of the field going quietly missing
        until the other model's hour runs out."""
        calls: list[dict] = []

        def answering(request: httpx.Request) -> httpx.Response:
            import json as _json

            calls.append(_json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    'choices': [{'message': {'content': '{"a": 1}'}}],
                    'usage': {},
                },
            )

        row_id = uuid.uuid4()
        refused = _connection()
        refused.id = row_id
        await OpenAiCompatibleClient(
            refused,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))
        calls.clear()

        switched = _connection()
        switched.id = row_id
        switched.model_name = 'deepseek-v4-flash'
        response = await OpenAiCompatibleClient(
            switched, _transport=httpx.MockTransport(answering)
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))

        assert response.content == '{"a": 1}'
        assert len(calls) == 1  # nothing taught this model to drop the key
        assert 'reasoning' in calls[0]

    async def test_a_changed_address_still_asks_the_question(self, stub_dns) -> None:
        """The row's address is editable — ``AiConnectionUpdate`` can point a
        saved row at another host — and the refusal belongs to the route it
        was learned on. A row moved to a host that accepts the key must ask
        rather than keep serving the previous host's hour."""
        from app.core.llm._optional_payload import remembered_rejections

        row_id = uuid.uuid4()
        calls: list[dict] = []
        learned = _connection()
        learned.id = row_id
        await OpenAiCompatibleClient(
            learned,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))
        assert len(calls) == 2  # refused once, retried without the key
        assert remembered_rejections(learned) == frozenset({'reasoning'})
        calls.clear()

        moved = _connection()  # the same saved row, pointed at another host
        moved.id = row_id
        # A host a save would accept: the write path resolves the name
        # (``guard_llm_url``), and an invented one never gets stored.
        moved.api_base_url = 'https://api.openai.com/v1'
        response = await OpenAiCompatibleClient(
            moved,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        ).complete(LlmRequest(prompt='Read the label.', disable_reasoning=True))

        assert response.content == '{"a": 1}'
        assert len(calls) == 2  # a new route, asked on its own merits
        assert 'reasoning' in calls[0]

    async def test_the_memory_expires_so_a_changed_route_is_relearned(self) -> None:
        from unittest.mock import patch

        from app.core.llm import _optional_payload

        calls: list[dict] = []
        conn = _connection()
        conn.id = uuid.uuid4()
        client = OpenAiCompatibleClient(
            conn,
            _transport=httpx.MockTransport(
                self._refusing_then_answering('reasoning', calls)
            ),
        )
        await client.complete(
            LlmRequest(prompt='Read the label.', disable_reasoning=True)
        )
        assert len(calls) == 2
        # The memory exists before expiry is simulated — otherwise the
        # assertion below passes for a memory that was never written.
        from app.core.llm._optional_payload import remembered_rejections

        assert remembered_rejections(conn) == frozenset({'reasoning'})

        calls.clear()
        with patch.object(_optional_payload.time, 'monotonic', return_value=1e12):
            response = await client.complete(
                LlmRequest(prompt='Read the label.', disable_reasoning=True)
            )
        assert response.content == '{"a": 1}'
        assert len(calls) == 2  # the hour passed; the question is asked again
        assert 'reasoning' in calls[0]

    def test_the_memory_keys_on_the_row_or_on_the_drafts_route(self) -> None:
        """Row memory is private to the row; draft memory is private to the
        draft's own address. Keying drafts by bare provider merged every
        organization's pre-save probe into one bucket — one org's refusal
        silenced another org's key for an hour. The model separates both:
        a refusal belongs to a model, not to the address it was asked at."""
        from app.core.llm._optional_payload import (
            remember_rejected_key,
            remembered_rejections,
        )

        row = _connection()
        row.id = uuid.uuid4()
        remember_rejected_key(row, 'reasoning')
        assert remembered_rejections(row) == frozenset({'reasoning'})

        stranger_row = _connection()
        stranger_row.id = uuid.uuid4()
        assert remembered_rejections(stranger_row) == frozenset()

        draft = _connection()  # unsaved: no id, the probe's own address
        remember_rejected_key(draft, 'response_format')
        same_route = _connection()
        assert remembered_rejections(same_route) == frozenset({'response_format'})

        other_route = _connection()
        other_route.api_base_url = 'https://api.openai.com/v1'
        assert remembered_rejections(other_route) == frozenset()

        other_model = _connection()  # same draft address, another model
        other_model.model_name = 'deepseek-v4-flash'
        assert remembered_rejections(other_model) == frozenset()

    def test_a_separator_inside_a_field_does_not_merge_two_routes(self) -> None:
        """The address and the model are free text from the connection form.
        Joined into one string with a separator, an address ending in
        ``|gpt-x`` with model ``mini`` and the bare address with model
        ``gpt-x|mini`` were the same key — two routes, one bucket."""
        from app.core.llm._optional_payload import (
            remember_rejected_key,
            remembered_rejections,
        )

        row_id = uuid.uuid4()
        for draft in (True, False):
            refused = _connection()
            refused.id = None if draft else row_id
            refused.api_base_url = 'https://api.openai.com/v1|gpt-x'
            refused.model_name = 'mini'
            remember_rejected_key(refused, 'reasoning')

            other = _connection()
            other.id = None if draft else row_id
            other.api_base_url = 'https://api.openai.com/v1'
            other.model_name = 'gpt-x|mini'
            assert remembered_rejections(refused) == frozenset({'reasoning'})
            assert remembered_rejections(other) == frozenset()

    def test_the_memory_reads_the_address_the_client_sends_to(self) -> None:
        """The clients strip a trailing slash, and the Anthropic client sends
        a connection naming no address to Anthropic's public API. One route
        written two ways is one route, and its refusal is remembered once."""
        from app.core.llm._optional_payload import (
            remember_rejected_key,
            remembered_rejections,
        )

        row_id = uuid.uuid4()
        bare = _connection()
        bare.id = row_id
        remember_rejected_key(bare, 'reasoning')
        slashed = _connection()
        slashed.id = row_id
        slashed.api_base_url = 'https://openrouter.ai/api/v1/'
        assert remembered_rejections(slashed) == frozenset({'reasoning'})

        unnamed = _connection('anthropic')
        unnamed.api_base_url = ''
        remember_rejected_key(unnamed, 'thinking')
        named = _connection('anthropic')
        named.api_base_url = 'https://api.anthropic.com/'
        assert remembered_rejections(named) == frozenset({'thinking'})


class TestTheAdapterAnswersForItsRowsProvider:
    """``connection_provider`` is what the usage ledger reads to book *who
    answered* — and every test that meets it elsewhere in the suite meets a
    double that sets the studied value itself: an ``AsyncMock`` asked for
    ``connection_provider`` answers with whatever it was told. Sabotaged to
    return ``None``, a real adapter would book every row as ``unknown`` and
    nothing here would notice. These three read the property off a real
    :class:`AiConnection` through each real adapter, so the booked name is
    the row's or the test is red."""

    def test_the_openai_compatible_adapter_reads_the_row(self) -> None:
        conn = _connection('ollama')
        client = OpenAiCompatibleClient(
            conn, _transport=httpx.MockTransport(_answering('{}'))
        )
        assert client.connection_provider == conn.provider

    def test_the_anthropic_adapter_reads_the_row(self) -> None:
        from app.core.llm.anthropic_client import AnthropicClient

        conn = _connection('anthropic')
        assert AnthropicClient(conn).connection_provider == conn.provider

    def test_the_google_adapter_reads_the_row(self) -> None:
        from app.core.llm.google_client import GoogleClient

        conn = _connection('google')
        assert GoogleClient(conn).connection_provider == conn.provider


class TestTheTransientDraftAndTheMemorysBounds:
    """The pre-save probe builds its row in memory, so nothing about it is
    persisted anywhere — including the organization the probe is for. And
    the refusal memory is a plain process-local dict: writing prunes it,
    so a flood of drafts naming their own hosts cannot grow it forever."""

    @pytest.fixture(autouse=True)
    def _clean_memory(self):
        from app.core.llm import _optional_payload

        _optional_payload._refused_since.clear()
        yield
        _optional_payload._refused_since.clear()

    def test_the_transient_draft_carries_its_organization(self) -> None:
        from app.services.ai_connection_service import AiConnectionService

        org_id = uuid.UUID('00000000-0000-0000-0000-000000000007')
        conn = AiConnectionService().build_transient(
            org_id=org_id,
            provider='anthropic',
            api_key_plaintext='sk-ant-test',
            api_base_url='https://api.anthropic.com',
            model_name='claude-sonnet-4-5',
        )
        assert conn.organization_id == org_id
        assert conn.id is None  # a draft: the memory keys it by org+route

    def test_writing_prunes_expired_entries(self) -> None:
        from unittest.mock import patch

        from app.core.llm import _optional_payload

        stale = _connection()
        _optional_payload.remember_rejected_key(stale, 'reasoning')
        assert len(_optional_payload._refused_since) == 1

        fresh = _connection()
        fresh.api_base_url = 'https://api.openai.com/v1'
        with patch.object(
            _optional_payload.time,
            'monotonic',
            return_value=1e12,  # the hour is long gone
        ):
            _optional_payload.remember_rejected_key(fresh, 'reasoning')

        assert list(_optional_payload._refused_since) == [
            (_optional_payload._connection_key(fresh), 'reasoning')
        ]

    def test_the_memory_never_grows_past_its_ceiling(self) -> None:
        from app.core.llm import _optional_payload

        for n in range(_optional_payload._MAX_MEMORY_ENTRIES + 10):
            conn = _connection()
            conn.api_base_url = f'https://host-{n}.example/api/v1'
            _optional_payload.remember_rejected_key(conn, 'reasoning')

        assert len(_optional_payload._refused_since) == (
            _optional_payload._MAX_MEMORY_ENTRIES
        )


class TestTheRefusalReachesHttpByItself:
    """The global handler in ``app.main`` maps the refusal for every route
    that lets it bubble — recipe import is the first outside vision, and the
    next caller will be another module. Pinned here so the mapping does not
    quietly disappear with a refactor of the app's handlers."""

    async def test_a_rejected_key_becomes_503_with_the_code_and_sentence(
        self,
    ) -> None:
        from starlette.requests import Request

        from app.core.llm.errors import LlmProviderRefusalError
        from app.main import llm_provider_refusal_handler

        request = Request(
            scope={
                'type': 'http',
                'method': 'POST',
                'path': '/api/v1/recipes/import/url',
                'headers': [],
                'query_string': b'',
            }
        )
        response = await llm_provider_refusal_handler(
            request,
            LlmProviderRefusalError(
                'OpenAI-compatible provider returned 401: {"error": "bad key"}',
                status_code=401,
                connection_name='Recipe Reader',
                model_name='gpt-4o-mini',
            ),
        )
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body['detail']['code'] == 'LLM_PROVIDER_KEY_REJECTED'
        assert 'Recipe Reader' in body['detail']['message']
        assert 'bad key' not in body['detail']['message']

    async def test_a_fault_with_no_specific_sentence_stays_generic(self) -> None:
        from starlette.requests import Request

        from app.core.llm.errors import LlmProviderRefusalError
        from app.main import llm_provider_refusal_handler

        request = Request(
            scope={
                'type': 'http',
                'method': 'GET',
                'path': '/api/v1/vision/extract',
                'headers': [],
                'query_string': b'',
            }
        )
        # Defensive: the type is only built for classified codes, but the
        # handler's fallback must still be total if that ever changes.
        response = await llm_provider_refusal_handler(
            request,
            LlmProviderRefusalError('weird', status_code=418),
        )
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body['detail']['code'] == 'LLM_PROVIDER_UNREACHABLE'
