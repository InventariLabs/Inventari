"""How long one model call may take, by the kind of provider behind it.

The clients used to carry ``timeout=60.0`` as a literal. That number is a
policy about somebody else's hardware, and it was wrong for half the
installations we recommend: a model on the user's own graphics card takes
minutes, not seconds, and answering that with "could not reach the provider"
sends them to check an address that was never the problem.
"""

from __future__ import annotations

from app.core.llm.enums import LlmProvider

#: The runtimes that run on hardware the user owns. Grouped in
#: :class:`LlmProvider` under the same heading, and the reason a longer
#: default is the right one rather than a raised limit for everybody: a cloud
#: endpoint silent for a minute is a broken call, and waiting five more
#: minutes on it costs a request slot and tells the reader nothing.
LOCAL_RUNTIMES = frozenset(
    {LlmProvider.OLLAMA.value, LlmProvider.LM_STUDIO.value, LlmProvider.VLLM.value}
)


def request_timeout(provider: str | None) -> float:
    """Seconds a completion call may take for a connection of *provider*.

    An unknown provider — a value from a newer version, or none at all —
    is treated as remote: the shorter limit is the safe answer when the
    question cannot be settled.
    """
    from app.config import settings

    if provider in LOCAL_RUNTIMES:
        return float(settings.LLM_LOCAL_REQUEST_TIMEOUT_SECONDS)
    return float(settings.LLM_REQUEST_TIMEOUT_SECONDS)
