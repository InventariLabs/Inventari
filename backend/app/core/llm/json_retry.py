"""One retry, with the model's mistake handed back to it.

:func:`app.core.llm.json_parsing.extract_json` salvages an answer that is
merely untidy. It cannot salvage one that is wrong — an object where a list
belongs, a number written out as prose. For that the only useful move is to
ask again and say what was wrong, which models are markedly good at fixing.

Scope, deliberately narrow:

* only parsing and validation failures are retried. A provider that timed out
  or returned 502 is a transport problem with its own handling, and asking it
  twice as fast is the wrong response. An answer with nothing in it is the
  third case, and it belongs on that side of the line too: there is no mistake
  to hand back, and a model that returned nothing returns nothing again. The
  observed cost of not knowing that was forty seconds and two bills for one
  silence.
* one extra call by default. A model that failed twice will not succeed on
  the fifth attempt, and the user is waiting.
* usage accounting stays with the caller, through ``on_response``. A retry
  costs tokens; both attempts have to be billed, not just the one that worked.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.core.llm.base import LlmClient, LlmRequest, LlmResponse
from app.core.llm.diagnostics import TRUNCATED_REASONS
from app.core.llm.errors import LlmEmptyAnswerError
from app.core.logging import get_logger

__all__ = ['complete_json', 'default_retry_prompt']

log = get_logger(__name__)

# How much of the failed answer is quoted back. Long enough for the model to
# recognise its own output, short enough not to double the prompt.
_PREVIOUS_LIMIT = 1000

_RETRY_INSTRUCTION = """\

---

Your previous answer could not be used.

Previous answer:
{previous}

Problem: {error}

Return the corrected JSON only. No explanation, no markdown fence."""


def default_retry_prompt(
    request: LlmRequest, previous: str, error: Exception
) -> LlmRequest:
    """Re-ask the original question with the failed answer appended.

    The original prompt is kept verbatim in front, so the retry is the same
    task with an added correction — not a new, thinner task. Everything else
    on the request (images, sampling, schema) carries over untouched.
    """
    correction = _RETRY_INSTRUCTION.format(
        previous=_truncate(previous, _PREVIOUS_LIMIT),
        error=error,
    )
    return replace(request, prompt=request.prompt + correction)


async def complete_json[T](
    client: LlmClient,
    request: LlmRequest,
    *,
    validate: Callable[[str], T],
    max_attempts: int = 2,
    build_retry_prompt: Callable[[LlmRequest, str, Exception], LlmRequest]
    | None = None,
    on_response: Callable[[LlmResponse], Awaitable[None]] | None = None,
) -> tuple[T, LlmResponse]:
    """Call ``client`` until ``validate`` accepts the answer.

    Args:
        client: Anything satisfying the ``LlmClient`` protocol.
        request: The first request. Never mutated — retries are copies.
        validate: Turns raw content into the caller's type, raising
            ``ValueError`` (which covers ``JSONDecodeError`` and
            ``LlmContractError``) or ``TypeError`` when the answer is unusable.
        max_attempts: Total calls, not extra ones. ``2`` is one retry.
        build_retry_prompt: Overrides how the correction is phrased.
        on_response: Awaited once per attempt, before validation, so the
            caller can log usage for calls that ended up being thrown away.

    Returns:
        The validated value and the response it came from.

    Raises:
        Whatever ``validate`` raised on the final attempt; whatever the client
        raised, immediately and without a retry.
    """
    if max_attempts < 1:
        raise RuntimeError('max_attempts must be at least 1')

    build_retry = build_retry_prompt or default_retry_prompt
    attempt_request = request

    for attempt in range(1, max_attempts + 1):
        # Outside the try on purpose: a transport failure must not be mistaken
        # for a model that answered badly, and must not be retried here.
        response = await client.complete(attempt_request)
        if on_response is not None:
            await on_response(response)

        # Also outside it, and for the same reason: an empty answer is not an
        # answer of the wrong shape. Raising inside the try would put it back
        # on the retry path the type exists to keep it off.
        if not response.content.strip():
            raise _empty_answer(client, response)

        try:
            return validate(response.content), response
        except (ValueError, TypeError) as err:
            if attempt == max_attempts:
                log.warning('LLM answer unusable after %d attempt(s): %s', attempt, err)
                raise
            log.info('LLM answer unusable (attempt %d), asking again: %s', attempt, err)
            attempt_request = build_retry(request, response.content, err)

    raise AssertionError('unreachable: the loop returns or raises on every path')


def _empty_answer(client: LlmClient, response: LlmResponse) -> LlmEmptyAnswerError:
    """Name the silence, and say what the provider gave as its reason for it.

    ``getattr`` rather than attribute access: the protocol is structural, and
    a test double that only implements ``complete`` is a legitimate client.
    """
    connection_name = getattr(client, 'connection_name', None)
    model_name = getattr(client, 'model_name', None)
    reason = response.finish_reason
    if reason in TRUNCATED_REASONS:
        detail = (
            f'the provider stopped at the token limit ({reason!r}), so the '
            'answer never got written'
        )
    elif reason:
        detail = f'the provider stopped with {reason!r}'
    else:
        detail = 'the provider gave no reason'
    log.warning(
        'LLM returned no content from %s/%s: %s',
        connection_name,
        model_name,
        detail,
    )
    return LlmEmptyAnswerError(
        f'The model returned no content — {detail}.',
        connection_name=connection_name,
        model_name=model_name,
        finish_reason=reason,
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + '… (truncated)'
