"""Unit tests for app.core.llm.base.

The core.llm.base module exports three public symbols (one Protocol, two
dataclasses) that everything else in core.llm (factory, registry,
clients) is built on. These tests pin:

- LlmRequest is constructable with sensible defaults so callers can
  ``LlmRequest(prompt=\"x\")`` without naming every multimodal flag.
- LlmResponse always carries a usage dict — even an empty one — so
  callers (``openai_client``, ``google_client``) can populate it
  unconditionally without worrying about ``None``.
- LlmClient is a Protocol that any adapter may satisfy structurally
  (no inheritance required) — verified by a duck-type test class.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import get_type_hints


class TestLlmRequest:
    def test_minimal_construction(self):
        from app.core.llm.base import LlmRequest

        req = LlmRequest(prompt='hello')
        assert req.prompt == 'hello'
        # Sensible defaults: text-only, no overrides.
        assert req.images is None
        assert req.system_prompt is None
        assert req.json_schema is None
        assert req.temperature is None
        assert req.max_tokens is None

    def test_multimodal_construction(self):
        from app.core.llm.base import LlmRequest

        req = LlmRequest(
            prompt='describe',
            images=[b'png-bytes-1', b'png-bytes-2'],
            system_prompt='you are a vision model',
        )
        assert req.images == [b'png-bytes-1', b'png-bytes-2']
        assert req.system_prompt == 'you are a vision model'

    def test_is_dataclass(self):
        """Dataclass lets adapters construct requests without learning a
        constructor signature — important because new modules will add
        optional fields over time."""
        from app.core.llm.base import LlmRequest

        assert is_dataclass(LlmRequest)

    def test_per_call_overrides_do_not_mutate_defaults(self):
        """Dataclass defaults are class-level. Setting
        ``LlmRequest(prompt, temperature=X)`` must not bleed X into
        subsequent constructions that omit it."""
        from app.core.llm.base import LlmRequest

        a = LlmRequest(prompt='a', temperature=0.7)
        b = LlmRequest(prompt='b')
        assert a.temperature == 0.7
        assert b.temperature is None


class TestLlmResponse:
    def test_minimal_construction(self):
        from app.core.llm.base import LlmResponse

        resp = LlmResponse(content='hi')
        assert resp.content == 'hi'
        assert resp.usage == {}
        assert resp.raw is None

    def test_usage_default_is_empty_dict_not_none(self):
        """Bugs happen when callers do ``resp.usage.get('x')`` on None;
        an empty dict is always safe to query."""
        from app.core.llm.base import LlmResponse

        resp = LlmResponse(content='')
        assert isinstance(resp.usage, dict)
        # .get returns None on missing keys — the property we want
        assert resp.usage.get('prompt_tokens') is None
        assert resp.usage.get('completion_tokens') is None

    def test_is_dataclass_with_field_names(self):
        """Pin the field surface — adding a new field is a deliberate
        review-time change, not a silent diff."""
        from app.core.llm.base import LlmResponse

        assert is_dataclass(LlmResponse)
        names = {f.name for f in fields(LlmResponse)}
        assert names == {'content', 'usage', 'raw', 'finish_reason'}


class TestLlmClientProtocol:
    def test_protocol_has_complete_async_method(self):
        """The factory in core/llm/factory.py calls
        ``await client.complete(request)`` and expects an
        LlmResponse back. If the Protocol's signature changes, that
        breaks the contract for every adapter."""
        from app.core.llm.base import LlmClient, LlmRequest, LlmResponse

        hints = get_type_hints(LlmClient.complete)
        assert hints['request'] is LlmRequest
        assert hints['return'] is LlmResponse

    def test_duck_typed_class_satisfies_protocol(self):
        """Any class with the right shape must be accepted without
        inheriting from LlmClient. This is what Protocol buys us —
        adapters don't need a base class."""
        from app.core.llm.base import LlmClient, LlmRequest, LlmResponse

        @dataclass
        class FakeAdapter:
            connection_name: str | None = None
            model_name: str | None = None
            connection_provider: str | None = None

            async def complete(self, request: LlmRequest) -> LlmResponse:
                return LlmResponse(content='ok')

            async def list_models(self) -> list[str]:
                return []

        adapter = FakeAdapter()
        # runtime_checkable is needed for isinstance() to work
        assert isinstance(adapter, LlmClient)
