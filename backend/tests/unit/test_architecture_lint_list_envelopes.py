"""Unit tests for the list-envelope guardrail.

The check makes one claim: a route that returns a collection declares a
documented pagination envelope, never a bare ``list[...]``. What it cannot
see is whether the envelope's page is the right page — that belongs to the
endpoint's own test. Here: a planted bare list is a finding, a baselined one
is a notice, and an exception without a reason is still a finding.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_list_envelopes import (
    _check_list_envelopes,
    collect_bare_list_routes,
)

_BARE_GET = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=list[ThingDTO])
async def list_things():
    return []
"""

_ENVELOPE = """
from fastapi import APIRouter

from app.schemas.pagination import PaginatedResponse

router = APIRouter()


@router.get('', response_model=PaginatedResponse[ThingDTO])
async def list_things():
    return PaginatedResponse.from_full_list([], offset=0, limit=50)
"""

_NOT_A_LIST = """
from fastapi import APIRouter

router = APIRouter()


@router.get('/{thing_id}', response_model=ThingDTO)
async def get_thing(thing_id: str):
    return None
"""

_REASONED = """
from fastapi import APIRouter

router = APIRouter()


@router.post(
    '/defaults',
    response_model=list[dict],  # list-envelope-exception: a bulk result, not a collection of rows
)
async def create_defaults():
    return []
"""

_REASON_TOO_SHORT = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=list[ThingDTO])  # list-envelope-exception: legacy
async def list_things():
    return []
"""

_ADD_API_ROUTE = """
router.add_api_route(
    '',
    list_things,
    response_model=list[ThingDTO],
    methods=['GET'],
)
"""

_RETURN_ANNOTATION = """
from fastapi import APIRouter

router = APIRouter()


@router.get('')
async def list_things() -> list[ThingDTO]:
    return []
"""

_RETURN_ANNOTATION_ENVELOPE = """
from fastapi import APIRouter

router = APIRouter()


@router.get('')
async def list_things() -> PaginatedResponse[ThingDTO]:
    return PaginatedResponse.from_full_list([], offset=0, limit=50)
"""

_RETURN_ANNOTATION_OVERRIDDEN = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=PaginatedResponse[ThingDTO])
async def list_things() -> list[ThingDTO]:
    return []
"""

_RETURN_ANNOTATION_DISABLED = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=None)
async def list_things() -> list[ThingDTO]:
    return []
"""

_RETURN_ANNOTATION_REASONED = """
from fastapi import APIRouter

router = APIRouter()


@router.get('')  # list-envelope-exception: the six fixed expiry buckets
async def list_buckets() -> list[BucketDTO]:
    return []
"""

_RETURN_ANNOTATION_NOT_A_ROUTE = """
async def helper() -> list[ThingDTO]:
    return []
"""

_OPTIONAL_PIPE = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=list[ThingDTO] | None)
async def list_things():
    return None
"""

_OPTIONAL_TYPING = """
from typing import Optional

from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=Optional[list[ThingDTO]])
async def list_things():
    return None
"""

_OPTIONAL_ENVELOPE = """
from fastapi import APIRouter

router = APIRouter()


@router.get('', response_model=PaginatedResponse[ThingDTO] | None)
async def list_things():
    return None
"""


def _tree(tmp_path: Path, source: str, name: str = 'things.py') -> Path:
    app_root = tmp_path / 'app'
    modules = app_root / 'modules'
    modules.mkdir(parents=True)
    (modules / name).write_text(source, encoding='utf-8')
    return app_root / 'modules'


def _keys(source: str, tmp_path: Path) -> set[str]:
    routes = collect_bare_list_routes([_tree(tmp_path, source)])
    return {route.key for route in routes}


class TestBareListRoutes:
    def test_a_get_route_answering_with_a_bare_array(self, tmp_path: Path):
        keys = _keys(_BARE_GET, tmp_path)

        assert keys == {'things.py::list_things@1'}

    def test_a_paginated_route_is_not_a_finding(self, tmp_path: Path):
        assert _keys(_ENVELOPE, tmp_path) == set()

    def test_a_single_resource_route_is_not_a_finding(self, tmp_path: Path):
        assert _keys(_NOT_A_LIST, tmp_path) == set()

    def test_a_reasoned_exception_is_not_a_finding(self, tmp_path: Path):
        assert _keys(_REASONED, tmp_path) == set()

    def test_an_exception_without_a_sentence_is_still_a_finding(self, tmp_path: Path):
        assert _keys(_REASON_TOO_SHORT, tmp_path) == {'things.py::list_things@1'}

    def test_an_add_api_route_registration(self, tmp_path: Path):
        assert len(_keys(_ADD_API_ROUTE, tmp_path)) == 1

    def test_a_second_route_in_the_same_function_gets_its_own_key(self, tmp_path: Path):
        source = _BARE_GET + _ADD_API_ROUTE

        assert _keys(source, tmp_path) == {
            'things.py::list_things@1',
            'things.py::<module>@1',
        }

    def test_a_bare_list_named_in_prose_is_not_a_finding(self, tmp_path: Path):
        source = '"""response_model=list[ThingDTO] is what this used to be."""\n'

        assert _keys(source, tmp_path) == set()

    def test_a_return_annotation_with_no_response_model_is_a_bare_array(
        self, tmp_path: Path
    ):
        assert _keys(_RETURN_ANNOTATION, tmp_path) == {'things.py::list_things@1'}

    def test_a_return_annotation_naming_an_envelope_is_not_a_finding(
        self, tmp_path: Path
    ):
        assert _keys(_RETURN_ANNOTATION_ENVELOPE, tmp_path) == set()

    def test_an_explicit_response_model_wins_over_the_return_annotation(
        self, tmp_path: Path
    ):
        assert _keys(_RETURN_ANNOTATION_OVERRIDDEN, tmp_path) == set()

    def test_response_model_none_publishes_no_array(self, tmp_path: Path):
        assert _keys(_RETURN_ANNOTATION_DISABLED, tmp_path) == set()

    def test_a_return_annotation_can_carry_a_reasoned_exception(self, tmp_path: Path):
        assert _keys(_RETURN_ANNOTATION_REASONED, tmp_path) == set()

    def test_a_list_returning_helper_that_is_not_a_route_is_not_a_finding(
        self, tmp_path: Path
    ):
        assert _keys(_RETURN_ANNOTATION_NOT_A_ROUTE, tmp_path) == set()

    def test_an_optional_list_response_model_written_with_a_pipe(self, tmp_path: Path):
        assert _keys(_OPTIONAL_PIPE, tmp_path) == {'things.py::list_things@1'}

    def test_an_optional_list_response_model_written_with_typing(self, tmp_path: Path):
        assert _keys(_OPTIONAL_TYPING, tmp_path) == {'things.py::list_things@1'}

    def test_an_optional_envelope_is_not_a_finding(self, tmp_path: Path):
        assert _keys(_OPTIONAL_ENVELOPE, tmp_path) == set()


class TestTheCheck:
    def test_a_bare_list_route_is_an_error(self, tmp_path: Path):
        root = _tree(tmp_path, _BARE_GET)

        findings = _check_list_envelopes([root])

        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert 'docs/subsystems/PAGINATION.md' in findings[0]
