"""The community quickstart's Path B steps work on the package it generates.

Path B once said "edit exactly as in Path A", whose steps describe a copy of
``example_widgets`` — a list endpoint, a page that sets its header. The package
``module new-community`` writes has neither, so the documented checkpoint
(``GET /api/v1/<module>`` answers an empty page) was a 404 and the pasted page
ended in "An error occurred".

The document now carries the package's own steps, each in a block preceded by
``<!-- quickstart-package: <file> <how> -->``. This test builds the package,
applies those blocks exactly as written, installs it (the install-time safety
scan reads the snippets' imports) and asks the list endpoint on a real
database. The page's type check and empty state are the frontend's side
(``frontend/src/test/communityQuickstartPackage.test.tsx``), which
reads the same blocks.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from app.core import module_migrations
from app.core.contracts import ModuleModelBase
from app.core.db_isolation import isolated_db_url
from manage import app

MODULE = 'warranty_tracker'

pytestmark = pytest.mark.integration

_BLOCK = re.compile(
    r'<!-- quickstart-package: (\S+) (replace|prepend|append|merge) -->\s*'
    r'```\w+\n(.*?)\n```',
    re.DOTALL,
)


def _documented_steps() -> list[tuple[str, str, str]]:
    root = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    document = (root / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')
    return _BLOCK.findall(document)


def _documented_empty_page() -> dict[str, object]:
    root = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    document = (root / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')
    shown = re.findall(r'`(\{"items": \[\][^`]*\})`', document)
    assert shown, 'the quickstart shows no empty page'
    return json.loads(shown[-1])


def _apply(package: Path, path: str, how: str, snippet: str) -> None:
    target = package / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if how == 'replace':
        target.write_text(snippet + '\n', encoding='utf-8')
    elif how == 'prepend':
        target.write_text(snippet + '\n' + target.read_text(encoding='utf-8'))
    elif how == 'append':
        target.write_text(target.read_text(encoding='utf-8') + '\n\n' + snippet + '\n')
    else:
        merged = json.loads(target.read_text(encoding='utf-8')) | json.loads(snippet)
        target.write_text(json.dumps(merged, indent=2) + '\n', encoding='utf-8')


def _insert(db_url: str, table, rows: list[dict[str, object]]) -> None:
    engine = create_engine(db_url)
    try:
        with engine.begin() as connection:
            connection.execute(table.insert(), rows)
    finally:
        engine.dispose()


def _open_transactions(db_url: str) -> int:
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    'select count(*) from pg_stat_activity where datname = '
                    "current_database() and state like 'idle in transaction%'"
                )
            ).scalar_one()
    finally:
        engine.dispose()


@pytest.fixture
def installed(tmp_path, monkeypatch) -> Iterator[Path]:
    """The scaffolded package with the quickstart applied, installed unsigned."""
    backend = tmp_path / 'install' / 'backend_modules'
    backend.mkdir(parents=True)
    frontend = tmp_path / 'install' / 'frontend_modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')

    runner = CliRunner()
    result = runner.invoke(
        app, ['module', 'new-community', MODULE, '--output', str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    for path, how, snippet in _documented_steps():
        _apply(tmp_path / MODULE, path, how, snippet)
    result = runner.invoke(
        app, ['module', 'install', str(tmp_path / MODULE), '--allow-unsigned']
    )
    assert result.exit_code == 0, f'{result.output}\n{result.exception!r}'

    import app.modules as app_modules

    monkeypatch.setattr(
        app_modules, '__path__', [str(backend), *list(app_modules.__path__)]
    )
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', backend)
    before = set(sys.modules)
    assert not ModuleModelBase.metadata.tables, 'a test left a module table on the base'
    yield backend / MODULE
    for name in set(sys.modules) - before:
        if name == f'app.modules.{MODULE}' or name.startswith(f'app.modules.{MODULE}.'):
            del sys.modules[name]
    ModuleModelBase.registry.dispose()
    ModuleModelBase.metadata.clear()


def test_the_quickstart_documents_the_package_steps() -> None:
    steps = {(path, how) for path, how, _ in _documented_steps()}

    assert ('backend/router.py', 'append') in steps
    assert ('frontend/pages/IndexPage.tsx', 'replace') in steps


def test_the_list_endpoint_the_quickstart_adds_answers_an_empty_page_then_the_rows(
    installed,
) -> None:
    from app.core.deps import get_async_db, require_org
    from app.database import Base
    from app.models.organization import Organization
    from app.models.user import User

    with isolated_db_url('community') as db_url:
        sync = create_engine(db_url)
        try:
            Base.metadata.create_all(
                sync, tables=[User.__table__, Organization.__table__]
            )
        finally:
            sync.dispose()
        module_migrations.run_module_migrations(MODULE, 'upgrade', db_url=db_url)

        from app.modules.warranty_tracker.models import Record
        from app.modules.warranty_tracker.router import router

        org_id, other_id = uuid4(), uuid4()
        _insert(
            db_url,
            Organization.__table__,
            [{'id': i, 'name': f'Org {i}'} for i in (org_id, other_id)],
        )

        engine = create_async_engine(
            db_url.replace('postgresql://', 'postgresql+asyncpg://', 1),
            poolclass=NullPool,
        )

        async def database():
            # Closed on the way out: a session left in its transaction holds
            # a lock the next test on this worker waits on, wiping the
            # scratch database.
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        api = FastAPI()
        api.include_router(router, prefix=f'/api/v1/{MODULE.replace("_", "-")}')
        # The module switch is a separate gate with its own tests; this one
        # asks what the quickstart's endpoint answers once it is on.
        api.dependency_overrides[router.dependencies[0].dependency] = lambda: True
        api.dependency_overrides[get_async_db] = database
        api.dependency_overrides[require_org] = lambda: org_id
        url = f'/api/v1/{MODULE.replace("_", "-")}'

        with TestClient(api) as client:
            empty = client.get(url)
            assert empty.status_code == 200, empty.text
            # The page the document says the endpoint answers, word for word.
            assert _documented_empty_page() == empty.json()
            assert empty.json() == {
                'items': [],
                'total': 0,
                'limit': 100,
                'offset': 0,
                'has_more': False,
                'total_capped': False,
            }

            _insert(
                db_url,
                Record.__table__,
                [
                    {'id': uuid4(), 'organization_id': org_id},
                    {'id': uuid4(), 'organization_id': other_id},
                ],
            )

            listed = client.get(url).json()
            assert listed['total'] == 1
            assert [set(row) for row in listed['items']] == [{'id', 'created_at'}]
            assert client.get(f'{url}?limit=0').status_code == 422

            assert _open_transactions(db_url) == 0, 'the endpoint left a session open'
