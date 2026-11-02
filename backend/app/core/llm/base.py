"""Public protocol and request/response dataclasses for the Core LLM
layer. Everything in :mod:`app.core.llm` (factory, registry, the
concrete ``OpenAiCompatibleClient`` and ``GoogleClient``) is built on
these three symbols.

Why a Protocol rather than a base class? Adapters live in feature code
across many files (vision, recipes, future modules). Forcing every
adapter to inherit ``LlmClient`` couples them to Core for no benefit.
``Protocol`` lets us keep the contract structural — any class with an
``async def complete(self, request: LlmRequest) -> LlmResponse`` is an
``LlmClient``.

The two dataclasses (``LlmRequest``, ``LlmResponse``) are intentionally
flat: no enums, no nested objects. They cross the network as JSON and
back; complex types would force adapters to re-parse them on every call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class LlmRequest:
    """A single call into an LLM client.

    Per-call overrides (``temperature``, ``max_tokens``) win over the
    connection-wide defaults loaded from :class:`AiConnection` — this is
    how callers opt into model-specific sampling (e.g. low-temperature
    extraction) without having to define a new connection.
    """

    prompt: str
    images: list[bytes] | None = None
    system_prompt: str | None = None
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    # Ask the provider to skip chain-of-thought reasoning. Reasoning models
    # (MiniMax-M3, DeepSeek-R1, o-series, Gemini thinking) bill CoT inside
    # ``completion_tokens``, so structured-output callers with a fixed
    # ``max_tokens`` budget can be starved into empty/truncated content.
    disable_reasoning: bool = False


@dataclass
class LlmResponse:
    """A single response from an LLM client.

    ``usage`` is always a dict (never None) — adapters populate it from
    the provider's native payload (``prompt_tokens``, ``completion_tokens``,
    ``total_tokens``); callers may rely on subscription without a guard.
    ``raw`` carries the original provider response for callers that need
    debugging output or chain-of-thought text. Keep it small — typically
    just the JSON body.

    ``finish_reason`` is a field of its own rather than something to dig out
    of ``raw``, because it is what separates "the model answered" from "the
    model was still thinking when the budget ran out" — two states that look
    identical from ``content`` alone once the reasoning wrapper is stripped,
    and are nothing alike to whoever is waiting. Adapters normalise it to the
    provider's own word (``length``, ``stop``, ``max_tokens``, ``MAX_TOKENS``)
    and leave it ``None`` when the provider said nothing.
    """

    content: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None
    finish_reason: str | None = None


@runtime_checkable
class LlmClient(Protocol):
    """Adapter contract: ``complete`` for chat, ``list_models`` for
    connection testing / model discovery.

    Marking the protocol ``@runtime_checkable`` lets us write
    ``isinstance(obj, LlmClient)`` in tests and in the factory, while
    still letting adapters satisfy the contract structurally (no
    inheritance required).
    """

    @property
    def connection_name(self) -> str | None:
        """The human-readable name of the :class:`AiConnection` behind this
        client, or ``None`` when the client was built without a connection
        row (a structural test double, the legacy env-var fallback).

        Read-only by design: the caller asks *which* connection answered so a
        failure message can name it, never to mutate the pool.
        """

    @property
    def model_name(self) -> str | None:
        """The model the connection points at, or ``None`` when unknown."""

    @property
    def connection_provider(self) -> str | None:
        """The provider behind this client (``ollama``, ``openrouter``, …),
        or ``None`` when the client was built without a connection row.

        Read-only by design: the usage ledger asks *who answered* so cost can
        be broken down per provider, never to mutate the pool.
        """

    async def complete(self, request: LlmRequest) -> LlmResponse: ...

    async def list_models(self) -> list[str]: ...
