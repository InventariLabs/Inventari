"""Unit tests for the audit-coverage gate.

The check's claim, stated narrowly enough to be true: a source that writes
(a mutating route, a CoreAPI namespace write method) must reach
``log_action_async`` in its own module or in Core. A reachable entry in a
sibling module is a different act's row — counting it is how document
cancel stayed invisible while the approval-request cascade beside it
journalled its own.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_audit_coverage import (
    _check_audit_coverage,
    _check_core_api_write_user_context,
    collect_audit_gaps,
)

_AUDIT_SERVICE = """
async def log_action_async(db, *, organization_id=None, target_id=None):
    db.add(object())
    await db.flush()
"""

_LOGGING_SERVICE = """
from app.services.audit import log_action_async


async def create_thing(db, org_id):
    db.add(object())
    await db.flush()
    await log_action_async(db, organization_id=org_id, target_id=1)
"""

_SILENT_SERVICE = """
async def create_thing(db, org_id):
    db.add(object())
    await db.flush()
"""

_READ_SERVICE = """
def render(rows):
    seen = set()
    for row in rows:
        seen.add(row)
    return seen
"""


def _write_app(tmp_path: Path, files: dict[str, str]) -> Path:
    app_root = tmp_path / 'app'
    for rel, source in {'services/audit.py': _AUDIT_SERVICE, **files}.items():
        path = app_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return app_root


_ROUTE = """
from fastapi import APIRouter

from app.services.things import create_thing

router = APIRouter()


@router.post('/things')
async def create_thing_route(db, org_id):
    return await create_thing(db, org_id)
"""

_READ_ROUTE = """
from fastapi import APIRouter

from app.services.things import render

router = APIRouter()


@router.post('/report')
async def report_route(rows):
    return render(rows)
"""

_DIRECT_LOG_ROUTE = """
from fastapi import APIRouter

from app.services.audit import log_action_async

router = APIRouter()


@router.patch('/things')
async def rename_thing(db, org_id):
    await log_action_async(db, organization_id=org_id, target_id=1)
"""

# The route-table form: ``app/api/storages/__init__.py`` registers its
# endpoints through ``add_api_route`` instead of decorators, and a scan
# that walks ``decorator_list`` alone never sees them.
_ROUTE_TABLE = """
from fastapi import APIRouter

from ._writes import create_thing

router = APIRouter()

router.add_api_route('/things', create_thing, methods=['POST'])
"""

_ROUTE_TABLE_SILENT = """
async def create_thing(db, org_id):
    db.add(object())
    await db.flush()
"""

_ROUTE_TABLE_LOGGING = """
from app.services.audit import log_action_async


async def create_thing(db, org_id):
    db.add(object())
    await db.flush()
    await log_action_async(db, organization_id=org_id, target_id=1)
"""


class TestWhatIsFlagged:
    def test_a_mutating_route_whose_service_never_journals(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _ROUTE, 'services/things.py': _SILENT_SERVICE},
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'api/things.py::create_thing_route'}

    def test_a_read_only_route_is_not_a_write(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _READ_ROUTE, 'services/things.py': _READ_SERVICE},
        )

        assert collect_audit_gaps(app) == {}

    def test_a_cross_module_cascade_does_not_cover_the_caller(self, tmp_path: Path):
        """The document-cancel shape: the sibling's row is the sibling's act."""
        documents = """
from fastapi import APIRouter

from app.modules.warehouse.service import cancel_document

router = APIRouter()


@router.patch('/warehouse/documents/{doc_id}/cancel')
async def cancel_route(db, org_id, doc_id):
    return await cancel_document(db, org_id, doc_id)
"""
        service = """
from app.modules.approvals.approvals_api import approvals_api


async def cancel_document(db, org_id, doc_id):
    db.add(object())
    await db.flush()
    await approvals_api.cancel_request(db, org_id, doc_id)
"""
        approvals = """
from app.services.audit import log_action_async


class ApprovalsAPI:
    async def cancel_request(self, db, org_id, doc_id):
        await log_action_async(db, organization_id=org_id, target_id=doc_id)


approvals_api = ApprovalsAPI()
"""
        app = _write_app(
            tmp_path,
            {
                'modules/warehouse/router.py': documents,
                'modules/warehouse/service.py': service,
                'modules/approvals/approvals_api.py': approvals,
            },
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'modules/warehouse/router.py::cancel_route'}

    def test_a_core_api_write_method_without_an_entry(self, tmp_path: Path):
        widgets = """
class CoreWidgetsAPI:
    async def create_async(self, db, org_id):
        db.add(object())
        await db.flush()
"""
        app = _write_app(tmp_path, {'core/public_api/widgets.py': widgets})

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'core/public_api/widgets.py::CoreWidgetsAPI.create_async'}

    def test_a_route_table_write_is_flagged(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {
                'api/things/__init__.py': _ROUTE_TABLE,
                'api/things/_writes.py': _ROUTE_TABLE_SILENT,
            },
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'api/things/_writes.py::create_thing'}

    def test_a_route_table_with_a_mixed_method_list_is_flagged(self, tmp_path: Path):
        table = _ROUTE_TABLE.replace("methods=['POST']", "methods=['GET', 'POST']")
        app = _write_app(
            tmp_path,
            {
                'api/things/__init__.py': table,
                'api/things/_writes.py': _ROUTE_TABLE_SILENT,
            },
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'api/things/_writes.py::create_thing'}

    def test_a_route_table_with_a_bare_string_method_is_flagged(self, tmp_path: Path):
        """FastAPI wraps ``methods='POST'`` into a set, so it registers a write."""
        table = _ROUTE_TABLE.replace("methods=['POST']", "methods='POST'")
        app = _write_app(
            tmp_path,
            {
                'api/things/__init__.py': table,
                'api/things/_writes.py': _ROUTE_TABLE_SILENT,
            },
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'api/things/_writes.py::create_thing'}

    def test_an_api_route_decorator_is_flagged(self, tmp_path: Path):
        route = """
from fastapi import APIRouter

from app.services.things import create_thing

router = APIRouter()


@router.api_route('/things', methods=['GET', 'POST'])
async def create_thing_route(db, org_id):
    return await create_thing(db, org_id)
"""
        app = _write_app(
            tmp_path,
            {'api/things.py': route, 'services/things.py': _SILENT_SERVICE},
        )

        gaps = collect_audit_gaps(app)

        assert set(gaps) == {'api/things.py::create_thing_route'}
        assert gaps['api/things.py::create_thing_route'].label == 'POST /things'

    def test_a_route_declared_inside_a_register_function_is_flagged(
        self, tmp_path: Path
    ):
        """The purchase-order and recipe routers declare handlers in a body."""
        app = _write_app(
            tmp_path,
            {'api/things.py': _NESTED_ROUTE, 'services/things.py': _SILENT_SERVICE},
        )

        gaps = collect_audit_gaps(app)

        key = 'api/things.py::register_thing_routes.create_thing_route'
        assert set(gaps) == {key}
        assert gaps[key].label == 'POST /things'


_NESTED_ROUTE = """
from fastapi import APIRouter


def register_thing_routes(router: APIRouter) -> None:
    @router.post('/things')
    async def create_thing_route(db, org_id):
        from app.services.things import create_thing

        return await create_thing(db, org_id)
"""


class TestWhatIsNot:
    def test_a_service_that_journals_covers_its_route(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _ROUTE, 'services/things.py': _LOGGING_SERVICE},
        )

        assert collect_audit_gaps(app) == {}

    def test_a_route_that_journals_itself(self, tmp_path: Path):
        app = _write_app(tmp_path, {'api/things.py': _DIRECT_LOG_ROUTE})

        assert collect_audit_gaps(app) == {}

    def test_a_core_api_write_method_that_journals(self, tmp_path: Path):
        widgets = """
from app.services.audit import log_action_async


class CoreWidgetsAPI:
    async def create_async(self, db, org_id):
        db.add(object())
        await db.flush()
        await log_action_async(db, organization_id=org_id, target_id=1)
"""
        app = _write_app(tmp_path, {'core/public_api/widgets.py': widgets})

        assert collect_audit_gaps(app) == {}

    def test_a_set_add_is_not_a_database_write(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _READ_ROUTE, 'services/things.py': _READ_SERVICE},
        )

        assert collect_audit_gaps(app) == {}

    def test_a_route_table_that_journals_covers_its_write(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {
                'api/things/__init__.py': _ROUTE_TABLE,
                'api/things/_writes.py': _ROUTE_TABLE_LOGGING,
            },
        )

        assert collect_audit_gaps(app) == {}

    def test_a_route_declared_inside_a_register_function_that_journals(
        self, tmp_path: Path
    ):
        app = _write_app(
            tmp_path,
            {'api/things.py': _NESTED_ROUTE, 'services/things.py': _LOGGING_SERVICE},
        )

        assert collect_audit_gaps(app) == {}

    def test_a_route_table_read_is_not_a_write(self, tmp_path: Path):
        table = _ROUTE_TABLE.replace("methods=['POST']", "methods=['GET']")
        app = _write_app(
            tmp_path,
            {
                'api/things/__init__.py': table,
                'api/things/_writes.py': _ROUTE_TABLE_SILENT,
            },
        )

        assert collect_audit_gaps(app) == {}

    def test_an_api_route_decorator_that_only_reads_is_not_a_write(
        self, tmp_path: Path
    ):
        route = _ROUTE.replace(
            "@router.post('/things')", "@router.api_route('/things', methods='GET')"
        )
        app = _write_app(
            tmp_path,
            {'api/things.py': route, 'services/things.py': _SILENT_SERVICE},
        )

        assert collect_audit_gaps(app) == {}


class TestTheRatchet:
    def test_a_baselined_gap_is_a_notice(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _ROUTE, 'services/things.py': _SILENT_SERVICE},
        )
        key = next(iter(collect_audit_gaps(app)))

        findings = _check_audit_coverage(app, {key})

        assert len(findings) == 1
        assert findings[0].startswith('::notice')

    def test_a_new_gap_is_an_error(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _ROUTE, 'services/things.py': _SILENT_SERVICE},
        )

        findings = _check_audit_coverage(app, set())

        assert findings[0].startswith('::error')
        assert 'audit_coverage_baseline.txt' in findings[0]

    def test_the_key_survives_the_lines_moving(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'api/things.py': _ROUTE, 'services/things.py': _SILENT_SERVICE},
        )
        key = next(iter(collect_audit_gaps(app)))

        moved = _write_app(
            tmp_path / 'moved',
            {
                'api/things.py': '# a new import\n# and a comment\n' + _ROUTE,
                'services/things.py': _SILENT_SERVICE,
            },
        )

        assert _check_audit_coverage(moved, {key})[0].startswith('::notice')


_NAMESPACE_PACKAGE_ROUTE = """
from fastapi import APIRouter

from app.modules.queue.services import queue_service as queue

router = APIRouter()


@router.post('/jobs')
async def claim_job(db, org_id):
    return await queue.claim(db, org_id)
"""


def test_a_submodule_of_a_package_without_init_is_followed(tmp_path: Path):
    """``services/`` has no ``__init__.py``; the import still names a module."""
    app = _write_app(
        tmp_path,
        {
            'modules/queue/router.py': _NAMESPACE_PACKAGE_ROUTE,
            'modules/queue/services/queue_service.py': _SILENT_SERVICE.replace(
                'create_thing', 'claim'
            ),
        },
    )

    assert list(collect_audit_gaps(app)) == ['modules/queue/router.py::claim_job']


_WIDGETS_WRITES = """
from app.core.contracts import UserContextDTO


class CoreWidgetsAPI:
    async def create_async(self, db, org_id, user_id):
        db.add(object())
        await db.flush()

    async def rename_async(self, db, widget_id, name, user: UserContextDTO):
        db.add(object())
        await db.flush()

    async def archive_async(self, db, widget_id, user: UserContextDTO | None = None):
        db.add(object())
        await db.flush()

    async def get_async(self, db, widget_id, user_id):
        return await db.get(object, widget_id)
"""


class TestACoreApiWriteTakesTheUser:
    """The rule the module guide states for a new CoreAPI write method."""

    def test_a_write_that_takes_an_id_for_the_user_is_an_error(self, tmp_path: Path):
        app = _write_app(tmp_path, {'core/public_api/widgets.py': _WIDGETS_WRITES})

        findings = _check_core_api_write_user_context(app)

        assert len(findings) == 1
        assert findings[0].startswith('::error file=app/core/public_api/widgets.py')
        assert 'core_api.CoreWidgetsAPI.create_async' in findings[0]
        assert 'UserContextDTO' in findings[0]

    def test_a_method_from_before_the_rule_is_a_notice(self, tmp_path: Path):
        app = _write_app(tmp_path, {'core/public_api/widgets.py': _WIDGETS_WRITES})

        findings = _check_core_api_write_user_context(
            app, {'core/public_api/widgets.py::CoreWidgetsAPI.create_async'}
        )

        assert [f.split(' ', 1)[0] for f in findings] == ['::notice']

    def test_a_module_api_is_not_the_core_facade(self, tmp_path: Path):
        app = _write_app(
            tmp_path,
            {'modules/widgets/widgets_api.py': _WIDGETS_WRITES},
        )

        assert _check_core_api_write_user_context(app) == []
