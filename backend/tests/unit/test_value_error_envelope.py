"""The 400 envelope stamps ``lang`` only on text i18n actually produced.

Every service ``ValueError`` reaches the client through the global handler
in ``app.main``. The handler used to copy ``str(exc)`` and stamp the request
language on it — a claim it could not keep: a Polish reader asking for a
production order without a recipe got an English sentence wearing a
``lang: pl`` label (measured on /maker/production at 390x844). Provenance
now rides on the type: ``ServiceRejectionError`` carries the i18n key it
was built from and earns the language field; a plain ``ValueError`` speaks
its own internal text and the envelope stops claiming otherwise.

Provenance decides the message itself, too (the rule:
the reader gets a generic sentence, the details go to the log): a sentence
this codebase wrote — a plain ``ValueError`` or a subclass defined under
``app.*`` — reaches the reader as-is; a library's subclass (pydantic's
``ValidationError`` names DTOs and echoes ``input_value``) never does.

What each test discriminates (the reviewer's measuring stick: revert the
handler and say which test falls):

- ``test_a_plain_value_error_carries_no_language_claim`` — falls on the
  old handler: it stamped ``lang`` on every ValueError it passed through.
- ``test_the_response_translates_in_the_readers_language_not_the_raises`` —
  falls on the old handler for the body, not just the label: the rejection
  is built under one language and answered under another, and the old
  handler returned the build-time sentence while claiming the answer-time
  language. The three remaining keyed tests pin the type's own contract
  (eager translation, kwargs, ``str(exc)``) and would survive a handler
  revert on purpose — they document ``ServiceRejectionError``, not the
  handler branch.
- ``test_a_library_value_error_answers_a_generic_message_not_its_text`` —
  falls on the old handler: it copied ``str(exc)`` of a pydantic
  ``ValidationError``, DTO name and ``input_value`` included, into the
  message the reader sees.
- ``test_a_builtin_subclass_of_value_error_answers_the_generic_message_too``
  — same fall, ``json.JSONDecodeError`` flavour: a builtin subclass is as
  little a business refusal as a library one.
- ``test_an_app_defined_marker_keeps_its_sentence`` — falls on a handler
  that genericises every subclass instead of asking where it was defined:
  ``StockUnavailableError`` is a refusal we wrote, its sentence is the
  reason the reader needs.
- ``test_a_plain_value_error_is_logged_with_its_traceback`` and
  ``test_a_keyed_rejection_is_not_logged`` — fall on the old handler both
  ways: it logged nothing, so a defect wearing a 400 left no traceback,
  and a handler that logs keyed rejections would spam every refusal.
"""

import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.i18n.service import (
    get_current_lang,
    get_error_message,
    set_current_lang,
)
from app.main import value_error_handler


def _request() -> SimpleNamespace:
    """A request stub carrying what the handler logs about the call."""
    return SimpleNamespace(method='POST', url=SimpleNamespace(path='/api/v1/x'))


async def test_a_plain_value_error_carries_no_language_claim() -> None:
    resp = await value_error_handler(
        _request(), ValueError('No recipe for this product')
    )

    detail = json.loads(resp.body)['detail']
    assert detail['code'] == 'VALIDATION_ERROR'
    assert detail['message'] == 'No recipe for this product'
    assert 'lang' not in detail


async def test_a_keyed_rejection_translates_and_earns_the_language() -> None:
    from app.core.exceptions import ServiceRejectionError

    exc = ServiceRejectionError('storage_not_found')
    resp = await value_error_handler(_request(), exc)

    lang = get_current_lang()
    detail = json.loads(resp.body)['detail']
    assert detail['message'] == get_error_message('storage_not_found', lang)
    assert detail['lang'] == lang


async def test_a_keyed_rejection_answers_with_its_key_as_the_code_in_every_language() -> (
    None
):
    """A client branches on ``code``; only ``message`` changes with the language.

    Falls on a handler that answers every refusal with ``VALIDATION_ERROR``:
    the reason the person was refused would then live only in the sentence.
    """
    from app.core.exceptions import ServiceRejectionError

    answers = {}
    for lang in ('en', 'pl'):
        set_current_lang(lang)
        try:
            resp = await value_error_handler(
                _request(), ServiceRejectionError('storage_type_in_use', count=3)
            )
        finally:
            set_current_lang(None)
        answers[lang] = json.loads(resp.body)['detail']

    assert answers['en']['code'] == answers['pl']['code'] == 'STORAGE_TYPE_IN_USE'
    assert answers['en']['message'] != answers['pl']['message']
    assert answers['pl']['message'] == get_error_message(
        'storage_type_in_use', 'pl', count=3
    )


async def test_the_response_translates_in_the_readers_language_not_the_raises() -> None:
    """The key wins over the build-time sentence.

    The rejection is raised while the request speaks English and answered
    while it speaks Polish (one connection, a language switch in between —
    or simply an eager translation racing a deferred response). The old
    handler returned the build-time English sentence wearing ``lang: pl``;
    the new one translates the key into the answering request's language.
    """
    from app.core.exceptions import ServiceRejectionError

    set_current_lang('en')
    exc = ServiceRejectionError('storage_not_found')
    set_current_lang('pl')
    try:
        resp = await value_error_handler(_request(), exc)
    finally:
        set_current_lang(None)

    detail = json.loads(resp.body)['detail']
    assert detail['message'] == get_error_message('storage_not_found', 'pl')
    assert detail['lang'] == 'pl'


async def test_a_counted_rejection_keeps_its_noun_in_the_readers_language() -> None:
    """A refusal whose noun agrees with a number is answered in that form.

    The handler translates the key again in the answering language; with the
    base row alone a single line read "lines 1 name" in English and
    "pozycje 1 wskazują" in Polish, so a refusal that needed the counted form
    could not travel keyed and was answered ``VALIDATION_ERROR``.
    """
    from app.core.exceptions import ServiceRejectionError

    set_current_lang('en')
    exc = ServiceRejectionError(
        'document_lines_need_stock_row', plural=1, type='OUT', lines='1'
    )
    set_current_lang('pl')
    try:
        resp = await value_error_handler(_request(), exc)
    finally:
        set_current_lang(None)

    detail = json.loads(resp.body)['detail']
    assert detail['code'] == 'DOCUMENT_LINES_NEED_STOCK_ROW'
    assert detail['message'].endswith('pozycja 1 wskazuje sam produkt')
    assert str(exc).endswith('line 1 names only a product')


async def test_a_keyed_rejection_formats_its_parameters() -> None:
    from app.core.exceptions import ServiceRejectionError

    exc = ServiceRejectionError('storage_type_in_use', count=3)
    resp = await value_error_handler(_request(), exc)

    lang = get_current_lang()
    detail = json.loads(resp.body)['detail']
    assert detail['message'] == get_error_message('storage_type_in_use', lang, count=3)


async def test_a_keyed_rejection_reads_as_its_translation_outside_the_handler() -> None:
    """``str(exc)`` stays the translated sentence, not the key.

    Email builders and background jobs catch ``ValueError`` and read
    ``str(exc)`` — the eager translation keeps them speaking the reader's
    language even where no response envelope exists.
    """
    from app.core.exceptions import ServiceRejectionError

    exc = ServiceRejectionError('storage_type_in_use', count=3)

    assert str(exc) == get_error_message(
        'storage_type_in_use', get_current_lang(), count=3
    )


def _pydantic_validation_error() -> ValidationError:
    """The leak as it really travels: an internal ``model_validate`` that
    fell over and escaped as a ``ValueError`` subclass."""
    return ValidationError.from_exception_data(
        'RecipeImportDTO', [{'type': 'missing', 'loc': ('name',), 'input': {}}]
    )


async def test_a_library_value_error_answers_a_generic_message_not_its_text() -> None:
    """pydantic's ``ValidationError`` subclasses ``ValueError``.

    The old handler copied its text into the response: the reader got the
    DTO's name and an ``input_value`` dump — internal vocabulary nobody
    chose to show. The generic sentence the reader earns instead is
    translated, so the envelope claims the language it was produced in.
    """
    exc = _pydantic_validation_error()
    resp = await value_error_handler(_request(), exc)

    detail = json.loads(resp.body)['detail']
    assert detail['code'] == 'VALIDATION_ERROR'
    assert detail['message'] == get_error_message('invalid_input', get_current_lang())
    assert detail['lang'] == get_current_lang()
    assert 'RecipeImportDTO' not in detail['message']
    assert 'input_value' not in detail['message']


async def test_a_builtin_subclass_of_value_error_answers_the_generic_message_too() -> (
    None
):
    """``json.JSONDecodeError`` is a builtin ``ValueError`` subclass.

    Builtin and library subclasses are equally not business refusals: no
    door of ours raises them at a reader on purpose.
    """
    exc = json.JSONDecodeError('Expecting value', 'doc', 0)
    resp = await value_error_handler(_request(), exc)

    detail = json.loads(resp.body)['detail']
    assert detail['code'] == 'VALIDATION_ERROR'
    assert detail['message'] == get_error_message('invalid_input', get_current_lang())
    assert 'Expecting value' not in detail['message']


async def test_an_app_defined_marker_keeps_its_sentence() -> None:
    """A ``ValueError`` subclass we defined is a refusal we wrote.

    ``StockUnavailableError`` travels with a sentence a reader can act on;
    the handler must not genericise it just because it is a subclass —
    provenance, not the shape of the inheritance, decides.
    """
    from app.core.exceptions import StockUnavailableError

    exc = StockUnavailableError(
        StockUnavailableError.NO_STOCK, 'Nothing of this product stands here'
    )
    resp = await value_error_handler(_request(), exc)

    detail = json.loads(resp.body)['detail']
    assert detail['code'] == 'VALIDATION_ERROR'
    assert detail['message'] == 'Nothing of this product stands here'


async def test_a_plain_value_error_is_logged_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 400 answered over a bare ``ValueError`` leaves a traceback.

    The handler cannot tell a business refusal from a defect wearing one,
    so every bare ``ValueError`` it answers is logged — the log is the
    census that separates the two afterwards.
    """
    try:
        raise ValueError('boom on a plain refusal path')
    except ValueError as caught:
        with caplog.at_level(logging.WARNING, logger='app'):
            await value_error_handler(_request(), caught)

    refused = [r for r in caplog.records if 'refused' in r.message]
    assert len(refused) == 1
    assert refused[0].exc_info is not None


async def test_a_keyed_rejection_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A keyed rejection is an expected refusal, not a defect candidate.

    Logging every one of them would bury the tracebacks the census is for.
    """
    from app.core.exceptions import ServiceRejectionError

    exc = ServiceRejectionError('storage_not_found')
    with caplog.at_level(logging.WARNING, logger='app'):
        resp = await value_error_handler(_request(), exc)

    assert resp.status_code == 400
    assert caplog.records == []


async def test_a_validator_refusal_carries_its_key_as_the_code_in_the_422_entry() -> (
    None
):
    """The 422's keyed entry names the refusal the way the 400 envelope does."""
    from fastapi.exceptions import RequestValidationError

    from app.core.exceptions import ServiceRejectionError
    from app.main import validation_exception_handler

    exc = RequestValidationError(
        [
            {
                'type': 'value_error',
                'loc': ('body', 'name'),
                'msg': 'Value error',
                'input': 'x',
                'ctx': {'error': ServiceRejectionError('storage_not_found')},
            }
        ]
    )
    resp = await validation_exception_handler(_request(), exc)

    entry = json.loads(resp.body)['detail'][0]
    assert resp.status_code == 422
    assert entry['code'] == 'STORAGE_NOT_FOUND'
    assert entry['msg'] == get_error_message('storage_not_found', get_current_lang())
