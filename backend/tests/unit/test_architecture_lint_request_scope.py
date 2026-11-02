"""Unit tests for the request-path tenant check.

The check makes one claim and it is worth stating precisely: an endpoint
that takes a database session must *use* something carrying the tenant.
Not that the query ends up filtered — that happens in a service, out of
this check's sight — but that the endpoint had the tenant to pass on. An
endpoint with no carrier at all cannot scope anything.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_request_scope import (
    _check_request_scope,
    collect_unscoped_endpoints,
)

_UNSCOPED = """
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get('/things')
async def list_things(db: AsyncSession = Depends(get_async_db)):
    return await core_api.things.list_async(db)
"""

_SCOPED_BY_ORG_ID = """
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get('/things')
async def list_things(
    org_id=Depends(require_org),
    db: AsyncSession = Depends(get_async_db),
):
    return await core_api.things.list_async(db, org_id)
"""

_SCOPED_BY_USER = """
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get('/things')
async def list_things(
    current_user=Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.list_things(db, current_user)
"""

_DECLARED_BUT_UNUSED = """
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get('/things')
async def list_things(
    current_user=Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db),
):
    return await core_api.things.list_async(db)
"""

_NO_SESSION = """
from fastapi import APIRouter

router = APIRouter()


@router.get('/health')
async def health():
    return {'ok': True}
"""

_ACTOR_ONLY = """
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post('/things/{thing_id}/block')
async def block_thing(
    thing_id,
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db),
):
    return await core_api.things.block_async(
        db, None, thing_id, actor_user_id=current_user.id
    )
"""


def _tree(tmp_path: Path, source: str, name: str = 'things.py') -> Path:
    app_root = tmp_path / 'app'
    (app_root / 'api').mkdir(parents=True, exist_ok=True)
    (app_root / 'api' / name).write_text(source, encoding='utf-8')
    return app_root


class TestWhatIsFlagged:
    def test_an_endpoint_with_no_carrier(self, tmp_path: Path):
        found = collect_unscoped_endpoints(_tree(tmp_path, _UNSCOPED))

        assert len(found) == 1
        assert next(iter(found)).endswith('::list_things')

    def test_a_carrier_declared_and_never_used(self, tmp_path: Path):
        """This is what a forgotten scoping looks like from the outside.

        The signature says current_user, the body hands the session on
        alone. Reading the signature would have called this scoped.
        """
        found = collect_unscoped_endpoints(_tree(tmp_path, _DECLARED_BUT_UNUSED))

        assert len(found) == 1

    def test_current_user_used_only_as_the_journal_actor(self, tmp_path: Path):
        """The call passes ``None`` for the organization: no tenant is held."""
        found = collect_unscoped_endpoints(_tree(tmp_path, _ACTOR_ONLY))

        assert len(found) == 1


class TestWhatIsNot:
    def test_an_endpoint_that_passes_the_org_id(self, tmp_path: Path):
        assert collect_unscoped_endpoints(_tree(tmp_path, _SCOPED_BY_ORG_ID)) == {}

    def test_an_endpoint_that_passes_the_user_on(self, tmp_path: Path):
        # Weaker than passing the id — the service reads organization_id
        # off it — and the shape most of the tree uses.
        assert collect_unscoped_endpoints(_tree(tmp_path, _SCOPED_BY_USER)) == {}

    def test_an_endpoint_that_never_touches_the_database(self, tmp_path: Path):
        assert collect_unscoped_endpoints(_tree(tmp_path, _NO_SESSION)) == {}

    def test_a_test_file(self, tmp_path: Path):
        app_root = tmp_path / 'app'
        (app_root / 'api' / 'tests').mkdir(parents=True)
        (app_root / 'api' / 'tests' / 'test_things.py').write_text(
            _UNSCOPED, encoding='utf-8'
        )

        assert collect_unscoped_endpoints(app_root) == {}


class TestTheRatchet:
    def test_a_baselined_endpoint_is_a_notice(self, tmp_path: Path):
        app_root = _tree(tmp_path, _UNSCOPED)
        key = next(iter(collect_unscoped_endpoints(app_root)))

        findings = _check_request_scope(app_root, {key})

        assert len(findings) == 1
        assert findings[0].startswith('::notice')

    def test_a_new_one_is_an_error(self, tmp_path: Path):
        app_root = _tree(tmp_path, _UNSCOPED)

        findings = _check_request_scope(app_root, set())

        assert findings[0].startswith('::error')
        assert 'request_scope_baseline.txt' in findings[0]

    def test_the_key_survives_the_lines_moving(self, tmp_path: Path):
        app_root = _tree(tmp_path, _UNSCOPED)
        key = next(iter(collect_unscoped_endpoints(app_root)))

        moved = _tree(tmp_path, '# a new import\n# and a comment\n' + _UNSCOPED)

        assert _check_request_scope(moved, {key})[0].startswith('::notice')
