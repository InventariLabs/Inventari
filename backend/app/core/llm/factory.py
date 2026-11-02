"""Single dispatch point for LLM provider → client adapter.

Dispatches on ``LlmProtocol`` (3 cases), not provider (16 values).
Per-provider quirks (Azure deployment URL, OpenRouter JSON-mode) live
inside the client, resolved via ``connection.provider``. This is the ONLY
place that picks a client class — every other call site goes through
:func:`app.core.llm.registry.get_client_for_purpose`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.llm.enums import LlmProtocol, protocol_for

if TYPE_CHECKING:
    from app.core.llm.base import LlmClient
    from app.models.ai_connection import AiConnection


def get_client(connection: AiConnection) -> LlmClient:
    """Return the adapter implementing :class:`LlmClient` for *connection*.

    Dispatch is on the wire protocol (3 cases), not the provider string
    (16 values). Adding a new OpenAI-compatible provider is zero backend
    code — just a descriptor entry on the frontend.
    """
    protocol = protocol_for(connection.provider)

    if protocol is None:
        # RuntimeError, like every "cannot call with this" seam in this
        # package (see secrets.decrypt_connection_secret): an internal
        # invariant, never a client's refusal — the resolver refuses
        # capability mismatches before a client is ever built.
        raise RuntimeError(
            f'{connection.provider} carries no LLM protocol — it is a reader '
            'key, not a model. Bind it to a purpose that wants the reader; '
            'a purpose that completes needs a model.'
        )

    if protocol == LlmProtocol.GOOGLE:
        from app.core.llm.google_client import GoogleClient

        return GoogleClient(connection)

    if protocol == LlmProtocol.ANTHROPIC:
        from app.core.llm.anthropic_client import AnthropicClient

        return AnthropicClient(connection)

    # OPENAI_COMPATIBLE — covers 14 of the 16 providers: OpenAI,
    # OpenRouter, Groq, DeepSeek, Mistral, Together, xAI, MiniMax, GLM,
    # MiMo, Ollama, LM Studio, vLLM, and the generic custom escape hatch.
    from app.core.llm.openai_client import OpenAiCompatibleClient

    return OpenAiCompatibleClient(connection)
