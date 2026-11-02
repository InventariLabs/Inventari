"""What the log has to say when a model's answer is not usable.

The line it used to leave was::

    LLM answer unusable after 2 attempt(s): LLM did not return JSON.
    Answer began: ''

Every word of which is about the answer *after* processing. The empty string
is what ``_strip_reasoning`` left behind, so the log showed exactly what had
been cut out and said nothing about what arrived. Three numbers separate the
three ways this happens — the model thought until the budget ran out, the
model declined, the model answered in prose — and all three were already in
hand and thrown away: ``finish_reason``, ``usage``, and the length of the
content before it was stripped.

Lives here rather than at each adapter so that "what a failed answer leaves
behind" is one decision. The recipes module had grown its own version of it;
nothing else had any.

On content: a model's answer can carry whatever was printed on the document
it just read. The full text is therefore a ``debug`` line — off unless
somebody turned it on to chase exactly this — while the three numbers, which
carry nothing from the document, are always logged.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ['TRUNCATED_REASONS', 'log_answer']

#: What the providers call "I stopped because the budget ran out". OpenAI-style
#: endpoints say ``length``, Anthropic ``max_tokens``, Google ``MAX_TOKENS``.
TRUNCATED_REASONS = frozenset({'length', 'max_tokens', 'MAX_TOKENS'})

#: How much of the raw answer a debug line carries. Long enough to see prose,
#: a refusal or an unclosed reasoning block for what it is.
_RAW_PREVIEW = 4000


def log_answer(
    logger: logging.Logger,
    *,
    content: str,
    raw_content: Any,
    finish_reason: str | None,
    usage: dict[str, int],
    connection_name: str | None = None,
    model_name: str | None = None,
) -> None:
    """Record what came back, in proportion to how wrong it is.

    Args:
        content: What the caller will see — after reasoning blocks are cut.
        raw_content: What the provider sent, before any of that.
        finish_reason: The provider's own word for why it stopped.
        usage: The provider's token counts.
        connection_name: Which connection answered, for a log a reader can act
            on without opening the database.
        model_name: The model behind that connection.
    """
    raw_text = raw_content if isinstance(raw_content, str) else ''
    truncated = finish_reason in TRUNCATED_REASONS
    empty = not content.strip()

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            'LLM answer from %s/%s: finish_reason=%r usage=%s raw=%r',
            connection_name,
            model_name,
            finish_reason,
            usage,
            raw_text[:_RAW_PREVIEW],
        )

    if not (empty or truncated):
        return

    logger.warning(
        'LLM answer %s from %s/%s: finish_reason=%r usage=%s raw_length=%d',
        'is empty' if empty else 'was cut off',
        connection_name,
        model_name,
        finish_reason,
        usage,
        len(raw_text),
    )
