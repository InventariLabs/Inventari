"""Standardized application exceptions for consistent HTTP error responses.

Usage in route handlers:
    raise NotFoundException('item', lang)
    raise ForbiddenException()
    raise UnprocessableException('...', '...', details={...})
"""

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from app.core.interceptors import InterceptorError
from app.core.llm.errors import LlmPurposeUnboundError
from app.i18n import Language
from app.i18n.service import (
    get_current_lang,
    get_error_message,
    get_plural_error_message,
)

T = TypeVar('T')


class AppException(HTTPException):
    """Base application exception that produces a structured error detail."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        detail = {'code': code, 'message': message}
        if field is not None:
            detail['field'] = field
        if extra:
            detail.update(extra)
        # ``headers`` stays a protocol concern, apart from the envelope: a
        # 401's ``WWW-Authenticate`` is read by the client's auth layer, not
        # by whatever renders the code and the sentence.
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class NotFoundException(AppException):
    """404 — resource not found.

    Without *lang* the sentence is in the request's language: the default
    used to be English, and every call site that did not pass the language
    answered a Polish reader in English.
    """

    def __init__(self, resource: str, lang: Language | None = None) -> None:
        i18n_key = f'{resource}_not_found'
        message = get_error_message(i18n_key, lang or get_current_lang())
        super().__init__(
            status_code=404,
            code=f'{resource.upper()}_NOT_FOUND',
            message=message,
        )


class ForbiddenException(AppException):
    """403 — access denied / missing organization."""

    def __init__(self, message: str = 'Forbidden', lang: Language = 'en') -> None:
        if message == 'Forbidden':
            message = get_error_message('forbidden', lang)
        super().__init__(status_code=403, code='FORBIDDEN', message=message)


class ConflictException(AppException):
    """409 — duplicate or conflicting resource.

    ``details`` lands verbatim in the structured ``detail`` payload, so
    callers can attach machine-readable context (e.g. ``conflicts`` rows)
    next to the human-readable message.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=409, code=code, message=message, extra=details)


class UnprocessableException(AppException):
    """422 — the request is well formed, and what it asks for cannot be done.

    ``details`` lands verbatim in the structured ``detail`` payload, like
    ``ConflictException``'s: a shortage dialog reads its rows there.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=422, code=code, message=message, extra=details)


class TooManyRequestsException(AppException):
    """429 — the caller stands at a limit on how much it may ask for.

    ``details`` lands verbatim in the structured ``detail`` payload, like
    ``ConflictException``'s: a screen labels the numbers of the limit from it.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=429, code=code, message=message, extra=details)


class EntityNotFoundError(LookupError):
    """Service-layer 'not found'. Mapped to 404 by ``map_service_errors``.

    Subclasses ``LookupError`` so routers that still catch the bare
    ``LookupError`` keep working — the migration can go endpoint by endpoint
    instead of big-bang.

    Carries a **resource slug**, not a sentence. The mapping builds a
    ``NotFoundException`` from it, and that class derives both the i18n key
    (``f'{resource}_not_found'``) and the machine code
    (``resource.upper() + '_NOT_FOUND'``) from the value — so a sentence here
    would produce ``code='RECIPE 42 NOT FOUND_NOT_FOUND'`` and echo the raw
    key back as the message. ``tests/unit/test_exception_resource_slugs.py``
    guards the direct ``NotFoundException`` call sites; this docstring is the
    guard for the indirect path.

    ``detail`` is for logs and for the routers that still format ``str(exc)``
    themselves; it never reaches the HTTP body once the decorator maps it.
    """

    def __init__(self, resource: str, detail: str | None = None) -> None:
        self.resource = resource
        super().__init__(detail or f'{resource} not found')


class ValidationException(AppException):
    """400 — invalid business input.

    ``code`` stays ``VALIDATION_ERROR`` unless the refusal names a catalogue
    key (see :func:`rejection_code`).
    """

    def __init__(
        self,
        message: str,
        field: str | None = None,
        extra: dict[str, Any] | None = None,
        code: str = 'VALIDATION_ERROR',
    ) -> None:
        super().__init__(
            status_code=400,
            code=code,
            message=message,
            field=field,
            extra=extra,
        )


def rejection_code(key: str) -> str:
    """The envelope ``code`` of the refusal catalogued under *key*."""
    return key.upper()


class ServiceRejectionError(ValueError):
    """A business-rule refusal whose text reaches a user.

    Services raise plain ``ValueError`` for these and the global handler in
    ``app.main`` maps them to 400 — but the handler cannot tell a
    reader-facing sentence from an internal invariant, so it stamped every
    response with ``lang`` while translating nothing: a Polish reader could
    get an English sentence labelled ``lang: pl``. The key is the proof of
    provenance — the handler translates keyed rejections with the request
    language and stamps ``lang`` truthfully; plain ``ValueError`` responses
    carry no language claim.

    Subclasses ``ValueError`` and translates eagerly (with the request
    language when raised inside one), so ``except ValueError`` blocks and
    ``str(exc)`` readers — email builders, background jobs — keep seeing
    the translated sentence, not the key.
    """

    def __init__(
        self, key: str, /, *, plural: int | None = None, **kwargs: Any
    ) -> None:
        self.key = key
        self.plural = plural
        self.kwargs = kwargs
        super().__init__(self.sentence(get_current_lang()))

    def sentence(self, lang: Language) -> str:
        """The refusal's sentence in *lang*, for every layer that translates it again.

        *plural* is the number the sentence's counted noun agrees with ("line 1
        names", "lines 1, 4 name"). The handlers translate a refusal again in the
        request language from the key; a refusal that needed the plural lookup
        could not travel as one, so it was raised as a plain ``ValueError`` and
        answered ``VALIDATION_ERROR`` instead of its key.
        """
        if self.plural is None:
            return get_error_message(self.key, lang, **self.kwargs)
        return get_plural_error_message(self.key, self.plural, lang, **self.kwargs)

    @property
    def code(self) -> str:
        """The machine code a client branches on: the catalogue key, upper-cased.

        Same spelling as every other code of the envelope (``ITEM_NOT_FOUND``);
        the sentence changes with the request language, the code never does.
        """
        return rejection_code(self.key)


class CodedRejectionError(ServiceRejectionError):
    """A catalogued refusal that also names the reason by a code of its own.

    The profile switch and focus mode answer ``409`` with a machine code a
    client branches on (``unknown_module``, ``already_in_focus``) that is not
    the upper-cased catalogue key, and with the structured context that
    explains it. Raised as ``Error('<key>', code='<machine code>', **context)``:
    ``code`` is that machine code, ``context`` the rest, and the sentence
    comes from the catalogue *key* in the request language — a list in the
    context is joined with commas for the sentence and stays a list here.
    """

    @property
    def code(self) -> str:
        return str(self.kwargs['code'])

    @property
    def context(self) -> dict[str, Any]:
        return {name: v for name, v in self.kwargs.items() if name != 'code'}

    def sentence(self, lang: Language) -> str:
        return get_error_message(
            self.key,
            lang,
            **{
                name: ', '.join(map(str, value))
                if isinstance(value, list | tuple)
                else value
                for name, value in self.kwargs.items()
            },
        )


class ContractViolationError(Exception):
    """A caller broke a Core contract; no reader is told anything.

    A module that emits a malformed event name, asks for a secret without
    naming it, or declares a settings schema the validator cannot read made
    a programming mistake. It is deliberately **not** a ``ValueError``: the
    global 400 handler shows a reader the text of every ``ValueError`` this
    codebase wrote, and these sentences are written for the developer who
    must fix the call. They surface as a 500 with the traceback in the log,
    which is what a defect in a caller deserves.
    """


class PeriodClosedError(ValueError):
    """Raised when a stock-mutating operation targets a closed inventory period.

    A plain ``ValueError`` marker (not an ``AppException``) so service-layer
    code can raise it freely; routers catch it explicitly and map to
    ``ConflictException('PERIOD_CLOSED')`` → HTTP 409. Defined in Core so
    every module can import it without a cross-module dependency on the
    warehouse module.
    """


class QuotaExceededError(PermissionError):
    """Raised when an organization stands at a limit it is configured with.

    A ``PermissionError`` because that is what it is to the reader — a
    refusal, 403 — but a type of its own, so that answering it does not mean
    answering every ``PermissionError`` that happens to travel the same call
    chain. :func:`map_service_errors` gives it the structured envelope
    (``FORBIDDEN`` with the message), the one shape the limit answers with
    through every door.
    """


class RoleInUseError(ValueError):
    """Raised when a custom role is deleted while somebody still holds it.

    A plain ``ValueError`` marker, like ``PeriodClosedError``: the service may
    raise it freely and the router maps it to 409. It carries the holder ids so
    the caller can say who stands in the way instead of only that somebody
    does.
    """

    def __init__(self, role_name: str, *, holders: list[UUID]) -> None:
        super().__init__(
            f'Role "{role_name}" is still held by {len(holders)} member(s)'
        )
        self.role_name = role_name
        self.holders = holders


class StockUnavailableError(ValueError):
    """Raised when a location cannot give up the stock an operation asked for.

    A plain ``ValueError`` marker, like ``PeriodClosedError`` and
    ``RoleInUseError``: the service raises it freely and the router's existing
    ``ValueError`` mapping turns it into a 400 with the message intact.

    It carries a **code** because the reason can have a second reader. The
    item service once decided whether to hydrate a quant for a legacy item
    by asking whether the refusal was "there is nothing here" rather than
    "there is not enough" — and it asked by testing
    ``'No stock found' in str(exc)``. That made an English sentence
    load-bearing: translating it, or rewording it to name the product instead
    of its UUID, would have switched the healing path off in silence. The code
    is the contract; the message is free to be a sentence a person can read.
    """

    #: Nothing of this product stands at this location at all.
    NO_STOCK = 'NO_STOCK'
    #: Some stands there, but every batch of it is quarantined or on hold.
    ALL_HELD = 'ALL_HELD'
    #: Some is available, but less than was asked for.
    NOT_ENOUGH = 'NOT_ENOUGH'

    def __init__(
        self,
        code: str,
        message: str,
        *,
        product_template_id: UUID | None = None,
        storage_location_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.product_template_id = product_template_id
        self.storage_location_id = storage_location_id


def is_reader_facing_value_error(exc: ValueError) -> bool:
    """Did this codebase write the sentence ``str(exc)`` speaks?

    A plain ``ValueError`` is what our services raise for business
    refusals (AGENTS.md §3), and every ``ValueError`` subclass defined
    under ``app.*`` is a deliberate marker of the same kind —
    ``StockUnavailableError``, ``ApprovalError``, ... — whose text a
    reader is meant to see. A library's subclass (pydantic's
    ``ValidationError``, ``json.JSONDecodeError``) was written for a
    programmer: its text names DTOs and echoes input values, so the
    answer it earns is a generic sentence plus a traceback in the log,
    never the library's words on the screen.

    A class defined here can still say its text is for operators — a
    ``reader_facing = False`` attribute (``LlmContractError``: it carries a
    preview of what the model sent) — and is answered like a library's.

    Provenance is decided by where the class was defined, not by the
    inheritance shape: the module a class was born in is the one fact
    that separates "a sentence we wrote" from "a sentence a library
    wrote", and it needs no registry that can drift.
    """
    exc_type = type(exc)
    if not getattr(exc_type, 'reader_facing', True):
        return False  # the class says its text is for logs
    return exc_type is ValueError or exc_type.__module__.startswith('app.')


def keyed_refusal(exc: ValueError) -> ServiceRejectionError | None:
    """The catalogued refusal *exc* is, or carries; ``None`` when it has none.

    A validator that refuses with ``ServiceRejectionError`` while a service
    builds a schema from the request reaches the caller wrapped in pydantic's
    ``ValidationError``, which is a library's ``ValueError``. The wrapper is
    pydantic's; the refusal inside it, in ``ctx['error']``, is a sentence we
    wrote under a key, and is answered like one — the 422 handler reads the
    same place.
    """
    if isinstance(exc, ServiceRejectionError):
        return exc
    if isinstance(exc, PydanticValidationError):
        for error in exc.errors():
            refusal = (error.get('ctx') or {}).get('error')
            if isinstance(refusal, ServiceRejectionError):
                return refusal
    return None


def refusal_text(exc: ValueError) -> str:
    """The sentence a router may hand on from a ``ValueError`` it caught.

    A router that maps a service's refusal to a status of its own — a 409, a
    404, a 413 — speaks the refusal's text. It used to speak ``str(exc)``,
    and a router-local catch then decided provenance by not deciding it:
    pydantic's ``ValidationError``, raised when a service builds a DTO from
    the request, reached a Polish reader as the DTO's name, the echoed input
    and a link to pydantic's docs, in English.

    The rule is the global handler's (:func:`is_reader_facing_value_error`).
    A sentence this codebase wrote is returned; a library's error is raised
    again, so it reaches the handler in ``app.main``, which logs its
    traceback and answers with the translated generic sentence.
    """
    if not is_reader_facing_value_error(exc):
        raise exc
    return str(exc)


def refusal_code(exc: ValueError, fallback: str) -> str:
    """The code a router answers with for a refusal it maps to a status of its own.

    The refusal's catalogue key when it has one; *fallback* — the router's
    code for the status it chose — only for a sentence raised without a key.
    A router that wrote its own code for every refusal of a call answered a
    taken partner code with ``PARTNER_CONFLICT`` and an open period's reopen
    with ``PERIOD_CLOSED``: the status may be the router's, the reason is
    the service's.
    """
    return exc.code if isinstance(exc, ServiceRejectionError) else fallback


def refusal_exception(exc: ValueError) -> ValidationException:
    """The 400 a router answers with for a refusal it caught itself.

    Same envelope as the global ``ValueError`` handler: a keyed refusal keeps
    its code and is translated into the request language, any other sentence
    this codebase wrote keeps ``VALIDATION_ERROR``, and a library's error is
    raised again (see :func:`refusal_text`). A router that wrapped
    ``refusal_text(exc)`` in a ``ValidationException`` by hand dropped the code.
    """
    keyed = keyed_refusal(exc)
    if keyed is not None:
        lang = get_current_lang()
        return ValidationException(
            keyed.sentence(lang), extra={'lang': lang}, code=keyed.code
        )
    return ValidationException(refusal_text(exc))


def catalogue_refusal(
    key: str,
    /,
    *,
    field: str | None = None,
    lang: Language | None = None,
    **kwargs: Any,
) -> ValidationException:
    """The 400 for the refusal catalogued under *key*, raised where it is decided.

    The envelope of a keyed ``ServiceRejectionError``: ``code`` is the key,
    upper-cased, and ``message`` its sentence in the request language. A
    router or service that built ``ValidationException(get_error_message(key))``
    — or a raw ``HTTPException`` with that sentence as ``detail`` — answered
    ``VALIDATION_ERROR`` or no code at all, so the reason a client could
    branch on stayed inside a translated sentence. Unlike the
    ``ServiceRejectionError`` it is not a ``ValueError``, so no
    ``except ValueError`` on the way out turns it into another answer.

    *field* names the request field the refusal is about, and fills a
    ``{field}`` in the sentence too — the same name in both places; *lang*
    overrides the request language (a sign-up answers in the language it
    chose); the other keyword arguments fill the sentence's placeholders.
    """
    lang = lang or get_current_lang()
    if field is not None:
        kwargs.setdefault('field', field)
    return ValidationException(
        get_error_message(key, lang, **kwargs),
        field=field,
        extra={'lang': lang},
        code=rejection_code(key),
    )


def catalogue_status_refusal(
    key: str,
    status_code: int,
    /,
    *,
    lang: Language | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> AppException:
    """:func:`catalogue_refusal` for a refusal answered at a status of its own.

    A 401, 403 or 404 whose sentence is in the catalogue used to be raised as
    ``HTTPException(detail=get_error_message(key, lang))``: the reader got the
    sentence in the right language and a client got a bare string with no
    code, so telling "this key may not create keys" from "the module is off"
    meant reading prose. The key becomes the ``code``, as for the 400s.
    *headers* stays beside the envelope — a 401's ``WWW-Authenticate``.
    """
    lang = lang or get_current_lang()
    return AppException(
        status_code=status_code,
        code=rejection_code(key),
        message=get_error_message(key, lang, **kwargs),
        extra={'lang': lang},
        headers=headers,
    )


def refusal_code_of(exc: BaseException) -> str | None:
    """The code a refusal carries, for a result that reports it outside an envelope.

    A batch answers 200 with one ``{..., 'error': <sentence>}`` row per item it
    refused, and the row carried only the sentence: a client could not tell a
    checked-out asset from a missing one without reading prose. This is the
    ``code`` beside it — the catalogue key of a keyed refusal, an
    interceptor's own code, the code of an envelope a nested call raised — or
    ``None`` for a sentence raised without one.
    """
    if isinstance(exc, ServiceRejectionError):
        return exc.code
    if isinstance(exc, InterceptorError):
        return exc.error_code
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        code = exc.detail.get('code')
        return code if isinstance(code, str) else None
    return None


def refusal_row(exc: ValueError, **where: Any) -> dict[str, Any]:
    """One refused row of a batch result: *where* it is, its sentence and its code.

    For a refusal the caller has already judged the reader's to see (see
    :func:`is_reader_facing_value_error`); ``code`` is left out for a sentence
    raised without one.
    """
    row: dict[str, Any] = {**where, 'error': str(exc)}
    code = refusal_code_of(exc)
    if code is not None:
        row['code'] = code
    return row


def _map_exception(exc: Exception) -> HTTPException | None:
    """Canonical HTTP counterpart for a service-layer exception.

    Returns ``None`` when *exc* must propagate unchanged — either because it is
    already an HTTP exception, or because it is not one of the mapped
    service-layer types (a stray ``TypeError`` stays a 500).

    Order matters: ``PeriodClosedError`` subclasses ``ValueError`` and must be
    matched first, or a closed period would surface as 400 instead of 409.

    Shared by both wrappers below — they previously carried identical
    six-branch ``except`` ladders, which is also what pushed the decorator past
    the C901 complexity guard when the ``EntityNotFoundError`` branch was added.
    """
    if isinstance(exc, HTTPException):
        return None  # AppException and friends are already correct
    if isinstance(exc, InterceptorError):
        return AppException(status_code=422, code=exc.error_code, message=exc.message)
    if isinstance(exc, LlmPurposeUnboundError):
        # A configuration gap, not a broken request: nobody has picked an AI
        # connection for the feature yet. The code lets a frontend name the
        # purpose from its own registry; the message stays generic because the
        # registry's human labels live in the frontend translations.
        return AppException(
            status_code=503,
            code='LLM_PURPOSE_UNBOUND',
            message=get_error_message('llm_purpose_unbound', get_current_lang()),
        )
    if isinstance(exc, EntityNotFoundError):
        # Deliberately NOT `LookupError` — that is the base class of KeyError
        # and IndexError, so a plain coding mistake anywhere under a decorated
        # endpoint would surface as a quiet 404 instead of the 500 it deserves.
        return NotFoundException(exc.resource, get_current_lang())
    if isinstance(exc, PeriodClosedError):
        return ConflictException('PERIOD_CLOSED', str(exc))
    if isinstance(exc, QuotaExceededError):
        return ForbiddenException(message=str(exc))
    if isinstance(exc, PermissionError):
        if not getattr(type(exc), 'reader_facing', True):
            return None  # the class says its text is for logs
        # One refusal, one shape: every other 4xx answer carries a code, and
        # the quota — a ``PermissionError`` of its own — already answers in
        # this envelope through the same branch above. A bare string here
        # would give the same refusal two shapes depending on which layer
        # mapped it.
        return ForbiddenException(message=str(exc))
    if isinstance(exc, ServiceRejectionError):
        # Same envelope contract as the global ValueError handler in app.main:
        # a keyed rejection is translated here and the envelope claims the
        # language the message is written in; a plain ValueError keeps its own
        # text, which this layer never processed, and travels unclaimed.
        return refusal_exception(exc)
    if isinstance(exc, ValueError):
        # A library's ValueError subclass is left to the global handler in
        # app.main, which logs the traceback and answers with the generic
        # sentence; mapping it here would answer with the library's words
        # and swallow both. Everything we wrote — a plain ValueError or an
        # app-defined marker — keeps §3's 400 with its own text.
        if not is_reader_facing_value_error(exc):
            return None
        # Structured envelope identical to the global ValueError handler in
        # app.main — keeps the {'detail': {'code', 'message'}} contract intact.
        return ValidationException(str(exc) or 'invalid input')
    return None


def map_service_errors(func: Callable[..., T]) -> Callable[..., T]:  # noqa: UP047
    """Decorator that maps service-layer exceptions to canonical HTTP responses.

    Mapping (per AGENTS.md §3):
    - ValueError → 400 (``ValidationException``, same structured envelope as the
      global ``ValueError`` handler in ``app.main``) — for ValueErrors this
      codebase wrote; a library's subclass (pydantic's ``ValidationError``) is
      left to that handler, which logs the traceback and answers with the
      generic sentence (see :func:`is_reader_facing_value_error`)
    - ``LlmPurposeUnboundError`` → 503 (``LLM_PURPOSE_UNBOUND`` — a feature
      whose AI connection was never picked; a configuration gap, not a fault)
    - PeriodClosedError → 409 (conflict — period is closed)
    - QuotaExceededError → 403 (``FORBIDDEN`` envelope with the message)
    - PermissionError → 403 (``FORBIDDEN`` envelope with the message)
    - InterceptorError → 422 (validation in interceptor pipeline)
    - EntityNotFoundError → 404 (translated, via the carried resource slug)
    - NotFoundException → 404
    - ConflictException → 409

    Note the asymmetry: ``EntityNotFoundError`` is mapped, its base class
    ``LookupError`` is not. Mapping the base would turn every stray
    ``KeyError``/``IndexError`` under the 38 decorated endpoints into a silent
    404 instead of the 500 it deserves.

    Typed ``AppException`` subclasses pass through untouched. Works on both
    sync and async functions (detected via ``asyncio.iscoroutinefunction``).
    """

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)  # type: ignore[misc,no-any-return]
        except Exception as exc:  # mapped to an app error or re-raised unchanged
            mapped = _map_exception(exc)
            if mapped is None:
                raise
            raise mapped from exc

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # mapped to an app error or re-raised unchanged
            mapped = _map_exception(exc)
            if mapped is None:
                raise
            raise mapped from exc

    if asyncio.iscoroutinefunction(func):
        return async_wrapper  # type: ignore[return-value]
    return sync_wrapper
