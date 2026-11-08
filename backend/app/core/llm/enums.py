"""Neutral enums for LLM providers, wire protocols, and capabilities.

The string values are load-bearing: persisted in ``ai_connections.provider``
(varchar) and mirrored as identity in the frontend type union
(``frontend/src/types/ai.ts``). Renaming a value is a breaking change.

Two-level model:
- ``LlmProvider`` (17 values) — what the user picks in the UI: sixteen
  model providers, mostly OpenAI-compatible ones that differ only by
  ``api_base_url``, and the Jina page reader, which is no model at all.
- ``LlmProtocol`` (3 values) — the wire protocol the client speaks. The
  factory dispatches on protocol, not provider, so adding a new provider
  that speaks OpenAI-compat is a one-line descriptor change with zero
  backend client code.

Provider → protocol mapping lives in ``protocol_for()`` below; the factory
imports it (single source of truth).
"""

from __future__ import annotations

from enum import StrEnum


class LlmProvider(StrEnum):
    # Cloud — native SDK adapters or distinct auth
    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'
    GOOGLE = 'google'

    # Aggregator
    OPENROUTER = 'openrouter'

    # Specialist / regional — OpenAI-compatible HTTP, only base_url differs
    GROQ = 'groq'
    DEEPSEEK = 'deepseek'
    MISTRAL = 'mistral'
    TOGETHER = 'together'
    XAI = 'xai'
    MINIMAX = 'minimax'
    GLM = 'glm'
    MIMO = 'mimo'

    # Local runtimes — OpenAI-compatible /v1 servers
    OLLAMA = 'ollama'
    LM_STUDIO = 'lm_studio'
    VLLM = 'vllm'

    # Escape hatch — user-supplied base_url + key
    OPENAI_COMPATIBLE = 'custom'

    # Reader service — a page-fetch key, not an LLM endpoint. No client is
    # built for it (``protocol_for`` answers ``None``) and the connection
    # test probes the reader directly instead of listing models.
    JINA = 'jina'


class LlmProtocol(StrEnum):
    """The actual wire protocol an adapter speaks. Many providers map to one."""

    OPENAI_COMPATIBLE = 'openai_compatible'
    ANTHROPIC = 'anthropic'
    GOOGLE = 'google'


# Single source of truth for provider → protocol. The factory imports this.
_OPENAI_COMPATIBLE_PROVIDERS: frozenset[str] = frozenset(
    {
        LlmProvider.OPENAI.value,
        LlmProvider.OPENROUTER.value,
        LlmProvider.GROQ.value,
        LlmProvider.DEEPSEEK.value,
        LlmProvider.MISTRAL.value,
        LlmProvider.TOGETHER.value,
        LlmProvider.XAI.value,
        LlmProvider.MINIMAX.value,
        LlmProvider.GLM.value,
        LlmProvider.MIMO.value,
        LlmProvider.OLLAMA.value,
        LlmProvider.LM_STUDIO.value,
        LlmProvider.VLLM.value,
        LlmProvider.OPENAI_COMPATIBLE.value,
    }
)


def protocol_for(provider: str) -> LlmProtocol | None:
    """Return the wire protocol for *provider*.

    Unknown providers default to OPENAI_COMPATIBLE — the safest assumption,
    since the OpenAI chat/completions shape is the de-facto standard.

    Providers without an LLM wire protocol answer ``None``: the Jina reader
    is a page-fetch service, not a model, so there is no adapter to
    dispatch to. The client factory refuses such a connection with a
    sentence rather than guess OpenAI-compatible — which is also what
    keeps the create form honest: a fixed-endpoint service owes no
    base URL.
    """
    if provider == LlmProvider.JINA.value:
        return None
    if provider == LlmProvider.ANTHROPIC.value:
        return LlmProtocol.ANTHROPIC
    if provider == LlmProvider.GOOGLE.value:
        return LlmProtocol.GOOGLE
    return LlmProtocol.OPENAI_COMPATIBLE


class LlmCapability(StrEnum):
    """Tags describing what a connection can do.

    Stored as ``list[str]`` JSONB on ``AiConnection``, so adding a new
    capability tag is a no-op at the schema layer. The registry resolver
    refuses connections whose ``capabilities`` list does not include the
    purpose's required capability.
    """

    VISION = 'vision'
    TEXT = 'text'
    # A page-fetch key: the connection carries credentials for an external
    # reader, not a model. A purpose with this capability never builds an
    # LlmClient — the consumer reads the key and fetches itself.
    URL_FETCH = 'url_fetch'
    # Future: EMBEDDING, TTS, STT
