"""Failure types for the Core LLM layer.

One distinction earns its own exception: *the provider never answered* versus
*the provider answered something we cannot use*. They look alike at the call
site and are nothing alike to the person waiting for the result — the first is
our outage, the second is a model that needs swapping. Collapsing both into
``RuntimeError`` is why an unreadable label used to surface as HTTP 500 with a
Python parser message in the body.

The transport side is named here too, and for the same reason. ``httpx``
raises ``ConnectError``, ``ConnectTimeout``, ``ReadTimeout`` and certificate
failures that inherit from none of the types a router thinks to catch, so a
provider that could not be reached at all came out of image recognition as
HTTP 500 with an empty body — 1.3 seconds in, before the model had been asked
anything.
"""

from __future__ import annotations

__all__ = [
    'LlmContractError',
    'LlmEmptyAnswerError',
    'LlmProviderRefusalError',
    'LlmPurposeUnboundError',
    'LlmTimeoutError',
    'LlmTransportError',
    'classify_provider_refusal',
    'provider_refusal',
    'transport_failure',
]


class LlmContractError(ValueError):
    """The provider answered, but not in the shape the caller asked for.

    Raised for prose instead of JSON, an envelope that unwraps to nothing, and
    values that do not fit the schema (``"weight_value": "about 500 g"``).

    Subclasses ``ValueError`` on purpose: call sites that already degrade on
    ``ValueError`` — the recipe parsers fall back to regex, translation keeps
    the original text — keep doing so without being told about a new type.

    The message is for the log: it quotes what the model sent. It is never a
    sentence for a reader — the routers that expose an AI feature re-say the
    failure with a catalogue key of their own, and one that escapes them is
    answered with the generic sentence (``reader_facing = False``), not with
    this text.

    ``connection_name`` / ``model_name`` are filled in by the Core facade once
    it knows which connection answered. They stay ``None`` when the error was
    raised without a client at hand, and must never carry secrets (no
    ``api_key_enc``, no ``api_base_url``).
    """

    reader_facing = False

    def __init__(
        self,
        *args: object,
        connection_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.connection_name = connection_name
        self.model_name = model_name


class LlmEmptyAnswerError(LlmContractError):
    """The provider answered, with nothing in it.

    Not a badly shaped answer — no answer. The distinction earns a type
    because the retry loop treats the two oppositely: an answer of the wrong
    shape is worth handing back to the model with the mistake named, and a
    model that returned nothing will return nothing again. Asking twice cost
    twenty seconds and a second bill for the same silence.

    The usual cause is a reasoning model spending the whole ``max_tokens``
    budget on chain-of-thought: the reasoning is billed as completion, the
    unclosed ``<think>`` block is stripped, and what reaches the caller is
    exactly the empty string. ``finish_reason`` is what tells that apart from
    a model that simply declined, so it travels with the error.

    Subclasses :class:`LlmContractError` so every router that already answers
    for an unusable answer keeps answering — a router that wants to name the
    silence specifically checks for this type first.
    """

    def __init__(
        self,
        *args: object,
        connection_name: str | None = None,
        model_name: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(*args, connection_name=connection_name, model_name=model_name)
        self.finish_reason = finish_reason


class LlmTransportError(RuntimeError):
    """The provider was never reached: connection refused, timeout, bad cert.

    "We could not get through to the model" and "the model answered something
    unusable" are one line apart at the call site and nothing alike to the
    reader: the first is an address, a certificate or a service that is down,
    the second is a model that needs swapping. Only the second is worth
    retaking the photograph for.

    Subclasses ``RuntimeError`` so call sites that already degrade on it —
    recipe parsing falls back to its own parser — keep degrading rather than
    learning a new type. Routers that want the distinction catch this first,
    and :mod:`app.main` maps it to 503 for everything that does not.
    """

    def __init__(
        self,
        *args: object,
        connection_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.connection_name = connection_name
        self.model_name = model_name


class LlmTimeoutError(LlmTransportError):
    """The provider was reached and did not answer in time.

    A subclass, because everything that degrades on a transport failure —
    recipe import falling back to its own parser, the 503 mapping in
    ``app.main`` — should keep degrading. What it changes is what the reader
    is told: "we could not reach the model" sends somebody to check an
    address, and the address was fine. The model was still thinking, which
    is what a model on the user's own graphics card does for minutes at a
    time (see ``app.core.llm.timeouts``).
    """


class LlmProviderRefusalError(RuntimeError):
    """The provider answered, refusing the request itself.

    Not an outage (nothing was reached) and not an unusable answer (the
    model erred, not the request): here the provider read us fine and said
    no about the key, the budget, or the model name. Those are the most
    common first-setup states — a key pasted with a typo, an expired key,
    a plan limit — and each is a settings change, which is why they must
    not arrive as "an internal error".

    ``status_code`` travels as data, so an HTTP layer can choose the
    sentence without matching on message text. Only codes the classifier
    names get this type; everything else keeps the plain ``RuntimeError``
    (see :func:`provider_refusal`).

    Subclasses ``RuntimeError`` on purpose: call sites that already
    degrade on it — recipe import falls back to its own parser — keep
    degrading without being told about a new type.
    """

    def __init__(
        self,
        *args: object,
        status_code: int,
        connection_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__(*args)
        self.status_code = status_code
        self.connection_name = connection_name
        self.model_name = model_name


def classify_provider_refusal(status_code: int) -> str | None:
    """The i18n key for a refusal this surface answers by name, or ``None``.

    The decision, made once for every provider client and every route fed
    by them (vision, the nutrition scanner, recipe import):

    * **401** — the key was rejected. The most common first-setup state.
    * **402 and 429** — out of budget or rate-limited. One sentence,
      because the reader's move is one move: check the plan, or try
      again shortly.
    * **404** — the model name does not exist at the provider. A typo in
      a setting, not a fault.
    * **everything else** — no specific action exists for the
      administrator, so it stays an internal error.
    """
    if status_code == 401:
        return 'llm_provider_key_rejected'
    if status_code in (402, 429):
        return 'llm_provider_limit'
    if status_code == 404:
        return 'llm_provider_model_unknown'
    return None


def provider_refusal(
    status_code: int,
    body: str,
    *,
    what: str,
    connection_name: str | None = None,
    model_name: str | None = None,
) -> RuntimeError:
    """Build the error for a provider's ``>= 400`` answer.

    Classified codes get :class:`LlmProviderRefusalError`; the rest keep
    the plain ``RuntimeError`` message they always had, so call sites that
    degrade on it are unaffected.
    """
    message = f'{what} returned {status_code}: {body[:500]}'
    if classify_provider_refusal(status_code) is None:
        return RuntimeError(message)
    return LlmProviderRefusalError(
        message,
        status_code=status_code,
        connection_name=connection_name,
        model_name=model_name,
    )


def transport_failure(
    exc: Exception,
    *,
    connection_name: str | None = None,
    model_name: str | None = None,
) -> LlmTransportError:
    """Build the transport error for a failure to hear from the provider.

    The exception type is part of the message on purpose: ``ConnectTimeout``,
    ``ConnectError`` and a certificate failure send an administrator to three
    different places, and ``httpx`` says which in the class name rather than
    in the text.
    """
    if _did_not_answer_in_time(exc):
        return LlmTimeoutError(
            f'The model did not answer within the time allowed '
            f'({type(exc).__name__}): {exc}',
            connection_name=connection_name,
            model_name=model_name,
        )
    return LlmTransportError(
        f'Could not reach the model provider ({type(exc).__name__}): {exc}',
        connection_name=connection_name,
        model_name=model_name,
    )


def _did_not_answer_in_time(exc: Exception) -> bool:
    """Whether *exc* says the provider was reached and was still answering.

    ``httpx`` names it with its own timeout types; an SDK on another HTTP
    stack (the Gemini SDK over ``aiohttp``) raises the standard
    ``TimeoutError``. Either way a timeout while connecting is an address
    that did not answer, not a model that was still thinking.
    """
    import httpx

    if isinstance(exc, httpx.TimeoutException):
        return not isinstance(exc, httpx.ConnectTimeout)
    if not isinstance(exc, TimeoutError):
        return False
    try:
        from aiohttp import ConnectionTimeoutError
    except ImportError:
        return True
    return not isinstance(exc, ConnectionTimeoutError)


class LlmPurposeUnboundError(RuntimeError):
    """No AI connection is bound to the purpose the caller asked for.

    A configuration gap, not a failure of the model or the network: nobody
    picked a connection for this feature yet. Named so a router can answer
    "set this up in Settings" instead of reporting an internal error about
    something the administrator can fix in a minute.
    """

    def __init__(self, purpose_key: str) -> None:
        super().__init__(
            f'No AI connection is bound to the "{purpose_key}" purpose for '
            'this organization. Configure one in Settings → AI Connections.'
        )
        self.purpose_key = purpose_key
