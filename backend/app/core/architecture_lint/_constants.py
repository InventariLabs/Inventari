from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Path roots. This module lives in app/core/architecture_lint/, so:
#   parents[2] -> app/   parents[1] -> app/core/
APP_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = Path(__file__).resolve().parents[1]

MODULES_ROOT = APP_ROOT / 'modules'
# Modules that live outside the repo tree: the compose mount a store-installed
# module sits in (``/modules-workspace``) and its host-side twin at the repo
# root. A module there is as much a table owner as one under app/modules, so
# the migration gate asks it too. Roots that do not exist are skipped.
EXTERNAL_MODULES_ROOTS = (
    Path('/modules-workspace'),
    APP_ROOT.parent.parent / 'modules-workspace',
)
API_ROOT = APP_ROOT / 'api'
PUBLIC_API_ROOT = APP_ROOT / 'core' / 'public_api'
CONTRACTS_ROOT = APP_ROOT / 'core' / 'contracts'
SERVICES_ROOT = APP_ROOT / 'services'
# backend/tests/ — the shared suite, a sibling of app/ rather than part of it.
TESTS_ROOT = APP_ROOT.parent / 'tests'

DEFAULT_BASELINE_FILE = CORE_DIR / 'architecture_lint_baseline.txt'
GET_DB_BASELINE_FILE = CORE_DIR / 'get_db_baseline.txt'
API_IMPORTS_BASELINE_FILE = CORE_DIR / 'architecture_lint_api_imports_baseline.txt'
MODULE_MIGRATIONS_BASELINE_FILE = CORE_DIR / 'module_migrations_baseline.txt'
MODULE_IMPORT_SURFACE_BASELINE_FILE = CORE_DIR / 'module_import_surface_baseline.txt'
SYNC_ASYNC_TWIN_BASELINE_FILE = CORE_DIR / 'sync_async_twin_baseline.txt'
TOCTOU_RISK_BASELINE_FILE = CORE_DIR / 'toctou_risk_baseline.txt'
TRANSACTION_OWNERSHIP_BASELINE_FILE = CORE_DIR / 'transaction_ownership_baseline.txt'
SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE = (
    CORE_DIR / 'services_public_api_import_baseline.txt'
)
TRANSACTION_ROLLBACK_BASELINE_FILE = CORE_DIR / 'transaction_rollback_baseline.txt'
TRANSACTION_OWNER_ALLOWLIST_FILE = CORE_DIR / 'transaction_owner_allowlist.txt'
BARE_EMIT_BASELINE_FILE = CORE_DIR / 'bare_emit_baseline.txt'
MIXED_STATUS_ASSERT_BASELINE_FILE = CORE_DIR / 'mixed_status_assert_baseline.txt'
REQUEST_SCOPE_BASELINE_FILE = CORE_DIR / 'request_scope_baseline.txt'
RAW_HTTP_EXCEPTION_BASELINE_FILE = CORE_DIR / 'raw_http_exception_baseline.txt'
CORE_API_MODEL_LEAK_BASELINE_FILE = CORE_DIR / 'core_api_model_leak_baseline.txt'
COREAPI_SIGNATURE_LEGALITY_BASELINE_FILE = (
    CORE_DIR / 'coreapi_signature_legality_baseline.txt'
)
CONTRACTS_SNAPSHOT_FILE = CORE_DIR / 'contracts_snapshot.json'
CORE_API_SNAPSHOT_FILE = CORE_DIR / 'core_api_snapshot.json'
MODULE_SDK_SNAPSHOT_FILE = CORE_DIR / 'module_sdk_snapshot.json'
ESCAPE_HATCH_ORG_FILTER_BASELINE_FILE = (
    CORE_DIR / 'escape_hatch_org_filter_baseline.txt'
)
ESCAPE_HATCH_QUERY_SCOPE_BASELINE_FILE = (
    CORE_DIR / 'escape_hatch_query_scope_baseline.txt'
)
PUBLIC_API_MISSING_ORG_BASELINE_FILE = CORE_DIR / 'public_api_missing_org_baseline.txt'
UNREAD_ORG_PARAMETER_BASELINE_FILE = CORE_DIR / 'unread_org_parameter_baseline.txt'
AUDIT_COVERAGE_BASELINE_FILE = CORE_DIR / 'audit_coverage_baseline.txt'
MANIFEST_PERMISSION_DEFERRALS_FILE = CORE_DIR / 'manifest_permission_deferrals.txt'
TEST_SKIP_BASELINE_FILE = CORE_DIR / 'test_skip_baseline.txt'
BASELINE_SIZES_FILE = CORE_DIR / 'baseline_sizes.txt'
# backend/scripts/, two levels above app/.
VULTURE_WHITELIST_FILE = APP_ROOT.parent / 'scripts' / 'vulture_whitelist.py'

FORBIDDEN_PREFIXES = ('app.models', 'app.database', 'app.services')
API_FORBIDDEN_IMPORT_PREFIXES = ('app.models', 'app.database')

ESCAPE_HATCH_MARKER = '# architecture: allow_direct_db_access'
REASON_PATTERN = re.compile(r'#\s*reason:\s*(.+)', re.MULTILINE)
REASON_MIN_WORDS = 5

FORBIDDEN_WRITES = (
    'db.commit()',
    'db.add(',
    'db.delete(',
    'db.merge(',
    'session.commit()',
    'session.add(',
    'session.delete(',
)

API_LAYER_FORBIDDEN_WRITES = (
    'db.add(',
    'db.delete(',
    'db.merge(',
    'session.add(',
    'session.delete(',
    'session.merge(',
)

CROSS_MODULE_WHITELIST_SUFFIXES: tuple[str, ...] = ('_api',)
CROSS_MODULE_WHITELIST_MODULES: frozenset[str] = frozenset({'exceptions', 'schemas'})

_MODEL_TO_API_SUGGESTIONS: dict[str, str] = {
    'app.models.item': 'core_api.items.get_async(db, org_id, item_id)',
    'app.models.storage_location': 'core_api.locations.get_async(db, org_id, storage_id)',
    'app.models.category': 'core_api.categories.list_async(db, org_id)',
    'app.models.product_template': 'core_api.product_templates.get_async(db, org_id, tpl_id)  or  core_api.product_templates.lookup_by_barcode_async(...)',
    'app.models.user': 'core_api.users.get_async(db, user_id)  or  core_api.users.list_org_members_async(...)',
    'app.models.partner': 'core_api.partners.get_async(db, org_id, partner_id)  or  core_api.partners.list_async(...)',
    'app.models.document': 'warehouse_api.create_and_confirm_document_async(...)  (from app.modules.warehouse.warehouse_api import warehouse_api)',
    'app.models.organization': 'core_api.organizations.get_async(db, org_id)',
}


def _suggest_fix(import_path: str) -> str:
    if import_path in _MODEL_TO_API_SUGGESTIONS:
        return _MODEL_TO_API_SUGGESTIONS[import_path]
    if import_path == 'app.models':
        return "Use 'from app.core.public_api import core_api' for the full API (22 namespaces)."
    if import_path.startswith('app.models.'):
        model_name = import_path.split('.')[-1]
        return f"No specific suggestion for '{model_name}'. Check core_api.* namespaces or see MODULES_GUIDE.md#data-access."
    return ''


@dataclass(frozen=True)
class Violation:
    file_path: Path
    line: int
    import_path: str

    def baseline_key(self, relative_to: Path) -> str:
        rel_path = self.file_path.relative_to(relative_to)
        return f'{rel_path}::{self.import_path}'


def _rel(p: Path) -> Path:
    try:
        return p.relative_to(Path.cwd())
    except ValueError:
        return p


def _rel_parts(file_path: Path, root: Path) -> tuple[str, ...]:
    """The file's parts below ``root`` — never the parts above it.

    Every "where does this file sit" predicate here reads this, because the
    absolute path answers a question nobody asked: a checkout under
    ``~/tests/inventari`` or ``/var/lib/jenkins/tests/workspace`` made
    ``'tests' in parts`` true for every file in the tree, and the checks
    gated on that predicate all fell silent at once — over a gate that
    still printed "Architecture lint passed" and exited 0.

    A path that is not below ``root`` (nothing in this package produces
    one — the walks all start at ``root``) keeps its own parts rather than
    raising, so a caller that passes an unrelated root degrades to the old
    reading instead of crashing the gate.
    """
    try:
        return file_path.relative_to(root).parts
    except ValueError:
        return file_path.parts


def _is_test_file(file_path: Path, root: Path) -> bool:
    parts = _rel_parts(file_path, root)
    return 'tests' in parts or file_path.name.startswith('test_')


def _is_model_file(file_path: Path) -> bool:
    """Recognise both ``models.py`` and files inside a ``models/`` package."""
    if file_path.name == 'models.py':
        return True
    return file_path.parent.name == 'models'
