"""Unit tests for the ``map_service_errors`` decorator (AGENTS.md §3).

Verifies the mapping of service-layer exceptions to canonical HTTP
exceptions and the pass-through of typed ``AppException`` subclasses,
for both sync and async wrapped functions.
"""

import asyncio

import pytest
from fastapi import HTTPException

from app.core.exceptions import (
    AppException,
    ConflictException,
    EntityNotFoundError,
    ForbiddenException,
    NotFoundException,
    PeriodClosedError,
    QuotaExceededError,
    ServiceRejectionError,
    map_service_errors,
)
from app.core.scoped_session import TenantIsolationError
from app.i18n.service import get_current_lang, get_error_message


class TestMapServiceErrorsSync:
    """Sync variant of the decorator."""

    def test_value_error_maps_to_400(self):
        @map_service_errors
        def failing_service():
            raise ValueError('invalid business input')

        with pytest.raises(HTTPException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == {
            'code': 'VALIDATION_ERROR',
            'message': 'invalid business input',
        }

    def test_keyed_rejection_maps_to_400_with_its_key_as_the_code(self):
        @map_service_errors
        def failing_service():
            raise ServiceRejectionError('storage_not_found')

        with pytest.raises(HTTPException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail['code'] == 'STORAGE_NOT_FOUND'
        assert excinfo.value.detail['message'] == get_error_message(
            'storage_not_found', get_current_lang()
        )

    def test_period_closed_error_maps_to_409(self):
        @map_service_errors
        def failing_service():
            raise PeriodClosedError('period is closed')

        with pytest.raises(ConflictException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 409

    def test_permission_error_maps_to_403(self):
        @map_service_errors
        def failing_service():
            raise PermissionError('access denied')

        with pytest.raises(ForbiddenException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {
            'code': 'FORBIDDEN',
            'message': 'access denied',
        }

    def test_interceptor_error_maps_to_422(self):
        from app.core.interceptors import InterceptorError

        @map_service_errors
        def failing_service():
            raise InterceptorError('item is currently lent out')

        with pytest.raises(AppException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail['message'] == 'item is currently lent out'

    def test_not_found_exception_passes_through(self):
        @map_service_errors
        def failing_service():
            raise NotFoundException('item')

        with pytest.raises(NotFoundException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 404

    def test_conflict_exception_passes_through(self):
        @map_service_errors
        def failing_service():
            raise ConflictException('DUPLICATE', 'duplicate name')

        with pytest.raises(ConflictException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 409

    def test_success_returns_result(self):
        @map_service_errors
        def ok_service():
            return {'ok': True}

        assert ok_service() == {'ok': True}


class TestMapServiceErrorsAsync:
    """Async variant of the decorator."""

    def test_value_error_maps_to_400(self):
        @map_service_errors
        async def failing_service():
            raise ValueError('invalid business input')

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(failing_service())
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == {
            'code': 'VALIDATION_ERROR',
            'message': 'invalid business input',
        }

    def test_permission_error_maps_to_403(self):
        @map_service_errors
        async def failing_service():
            raise PermissionError('access denied')

        with pytest.raises(ForbiddenException) as excinfo:
            asyncio.run(failing_service())
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {
            'code': 'FORBIDDEN',
            'message': 'access denied',
        }

    def test_interceptor_error_maps_to_422(self):
        from app.core.interceptors import InterceptorError

        @map_service_errors
        async def failing_service():
            raise InterceptorError('item is currently lent out')

        with pytest.raises(AppException) as excinfo:
            asyncio.run(failing_service())
        assert excinfo.value.status_code == 422

    def test_not_found_exception_passes_through(self):
        @map_service_errors
        async def failing_service():
            raise NotFoundException('item')

        with pytest.raises(NotFoundException) as excinfo:
            asyncio.run(failing_service())
        assert excinfo.value.status_code == 404

    def test_success_returns_result(self):
        @map_service_errors
        async def ok_service():
            return {'ok': True}

        assert asyncio.run(ok_service()) == {'ok': True}


class TestEntityNotFoundMapping:
    """``EntityNotFoundError`` → 404, but its base ``LookupError`` must not be.

    Mapping the base class would turn every stray ``KeyError`` / ``IndexError``
    under the 38 decorated endpoints into a quiet 404 instead of the 500 that
    exposes the bug.
    """

    def test_entity_not_found_maps_to_404(self):
        @map_service_errors
        def failing_service():
            raise EntityNotFoundError('recipe', 'Recipe 42 not found')

        with pytest.raises(NotFoundException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 404

    def test_mapped_body_is_a_clean_translated_envelope(self):
        """The slug — not the ``detail`` sentence — drives code and message.

        Passing the sentence through would produce
        ``code='RECIPE 42 NOT FOUND_NOT_FOUND'`` and echo the raw i18n key
        back as the message.
        """

        @map_service_errors
        def failing_service():
            raise EntityNotFoundError('recipe', 'Recipe 42 not found')

        with pytest.raises(NotFoundException) as excinfo:
            failing_service()
        detail = excinfo.value.detail
        assert detail == {
            'code': 'RECIPE_NOT_FOUND',
            'message': get_error_message('recipe_not_found', 'en'),
        }
        assert ' ' not in detail['code']

    @pytest.mark.parametrize('exc_type', [KeyError, IndexError])
    def test_plain_lookup_errors_are_not_swallowed(self, exc_type):
        @map_service_errors
        def buggy_service():
            raise exc_type('programming mistake')

        with pytest.raises(exc_type):
            buggy_service()

    def test_async_variant_maps_the_same_way(self):
        @map_service_errors
        async def failing_service():
            raise EntityNotFoundError('production_order')

        with pytest.raises(NotFoundException) as excinfo:
            asyncio.run(failing_service())
        assert excinfo.value.detail['code'] == 'PRODUCTION_ORDER_NOT_FOUND'

    def test_default_detail_is_derived_from_the_slug(self):
        exc = EntityNotFoundError('cost_line')
        assert exc.resource == 'cost_line'
        assert str(exc) == 'cost_line not found'

    def test_unmapped_exception_propagates_unchanged(self):
        """The refactor to a shared ``_map_exception`` widened the wrapper to
        ``except Exception``; anything unmapped must still bubble out as-is."""

        @map_service_errors
        def buggy_service():
            raise TypeError('not a service error')

        with pytest.raises(TypeError, match='not a service error'):
            buggy_service()


class TestLlmPurposeUnboundMapping:
    """An unbound AI purpose is a configuration gap, not a broken request.

    Left unmapped it used to fall through to the global handler as a 500
    carrying the raw purpose key inside two glued sentence prefixes.
    """

    def test_maps_to_503_with_a_code_and_without_the_raw_key(self):
        from app.core.llm.errors import LlmPurposeUnboundError

        @map_service_errors
        def failing_service():
            raise LlmPurposeUnboundError('recipes.text_parse')

        with pytest.raises(AppException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 503
        detail = excinfo.value.detail
        assert detail['code'] == 'LLM_PURPOSE_UNBOUND'
        assert 'recipes.text_parse' not in detail['message']

    def test_the_transport_errors_stay_out_of_the_way(self):
        """``LlmPurposeUnboundError`` subclasses ``RuntimeError``; the mapping
        must key on the type itself so transport failures keep their own 503
        message rather than being told to go configure something."""

        from app.core.llm.errors import LlmTransportError

        @map_service_errors
        def failing_service():
            raise LlmTransportError('connection refused')

        with pytest.raises(LlmTransportError):
            failing_service()


class TestLibraryValueErrorsAreNotMapped:
    """A library's ``ValueError`` subclass is a defect, not a §3 refusal.

    pydantic's ``ValidationError`` subclasses ``ValueError`` and names DTOs
    and ``input_value`` in its text. Mapping it here would answer it with
    a 400 carrying the library's words and swallow the traceback; leaving
    it alone hands it to the global ``ValueError`` handler in ``app.main``,
    which logs the traceback and answers with the generic sentence
    (the rule: the reader gets 4xx with a generic
    message, the details go to the log).
    """

    def test_a_pydantic_validation_error_propagates_to_the_global_handler(self):
        from pydantic import ValidationError

        @map_service_errors
        def buggy_service():
            raise ValidationError.from_exception_data(
                'RecipeImportDTO',
                [{'type': 'missing', 'loc': ('name',), 'input': {}}],
            )

        with pytest.raises(ValidationError):
            buggy_service()

    def test_an_app_defined_marker_still_maps_with_its_sentence(self):
        """``StockUnavailableError`` subclasses ``ValueError`` on purpose.

        A subclass defined under ``app.*`` is a refusal we wrote; the 400
        with its own text is the contract its raisers rely on.
        """
        from app.core.exceptions import StockUnavailableError

        @map_service_errors
        def failing_service():
            raise StockUnavailableError(
                StockUnavailableError.NO_STOCK,
                'Nothing of this product stands at this location',
            )

        with pytest.raises(HTTPException) as excinfo:
            failing_service()
        assert excinfo.value.status_code == 400
        assert (
            excinfo.value.detail['message']
            == 'Nothing of this product stands at this location'
        )


class TestTheLimitAndTheGuardAreEachTheirOwn:
    """The item limit is a refusal with its own envelope; the tenant guard is not a refusal.

    Both used to travel as a bare ``PermissionError``, so whatever answered
    one answered the other: a route that caught the limit also caught the
    guard's message — table names, row ids, the organization's id — and sent
    it to the client as the reason for a 403.
    """

    def test_the_item_limit_answers_in_the_forbidden_envelope(self):
        @map_service_errors
        def at_the_limit():
            raise QuotaExceededError('Item limit reached for this organization.')

        with pytest.raises(AppException) as excinfo:
            at_the_limit()
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {
            'code': 'FORBIDDEN',
            'message': 'Item limit reached for this organization.',
        }

    def test_a_tenant_isolation_violation_is_left_to_the_global_handler(self):
        @map_service_errors
        async def crossing():
            raise TenantIsolationError('Tenant isolation violation: Item ...')

        with pytest.raises(TenantIsolationError):
            asyncio.run(crossing())
