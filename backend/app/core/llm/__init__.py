"""Core LLM infrastructure: connection pool, client factory, purpose registry.

This package is owned by Core and is vertical-neutral — every AI/LLM
service in Inventari resolves a client through
:func:`app.core.llm.registry.get_client_for_purpose`, never by branching
on a ``provider`` string in feature code.

Directory layout:
    enums.py              -- LlmProvider, LlmCapability
    base.py               -- LlmRequest, LlmResponse, LlmClient protocol
    json_parsing.py       -- resilient JSON extraction from model output
    secrets.py            -- encrypt/decrypt/mask connection secret
    factory.py            -- get_client(connection): only dispatch point
    purpose_registry.py   -- register_ai_purpose / get_purpose / all_purposes
    registry.py           -- get_client_for_purpose: resolve + capability check
    openai_client.py      -- OpenAiCompatibleClient
    google_client.py      -- GoogleClient (native SDK)
"""

from app.core.llm.enums import LlmCapability, LlmProvider

__all__ = ['LlmProvider', 'LlmCapability']
