"""An endpoint that touches the database must hold the tenant in its hand.

ADR-008 counts ``_require_org()`` in routers as a layer of isolation. It
was not a layer, it was a habit: nothing anywhere failed when an endpoint
took a database session and never went near the organization. The layer
that was supposed to back it up — ``ModuleScopedSession``, the only one
that filters by itself — runs in three background jobs and nowhere in the
request path.

What this checks, stated narrowly enough to be true: an endpoint that
takes a database session must *use*, in its body, something that carries
the tenant. Not that the query ends up filtered — an endpoint hands the
work to a service and the filter happens there — but that the endpoint
had the tenant to hand it. An endpoint with no carrier at all cannot
scope anything, whatever the service does.

The baseline holds the endpoints that legitimately have no organization:
superuser views that span tenants by definition, everything that runs
before a session exists (login, registration, password reset), and the
public attestation pages reached by a signed token. They are the answer
to "which endpoints are global", written down instead of assumed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._constants import _is_test_file, _rel, _rel_parts
from ._run_cache import once_per_run

#: Names that carry the tenant into the work an endpoint delegates.
#: ``current_user``/``user_context`` carry it indirectly — the service
#: reads ``organization_id`` off them — which is weaker than passing the
#: id, and is the shape most of the tree uses.
_TENANT_CARRIERS = (
    'require_org',
    'organization_id',
    '_require_org_id',
    'org_id',
    'user_storage_ids',
    'tenant_session',
    'current_user',
    'user_context',
    'ctx',
)

#: Parameter annotations and defaults that mean "this endpoint reads or
#: writes the database".
_SESSION_HINTS = ('AsyncSession', 'Session', 'get_async_db', 'get_db')

_HTTP_METHODS = frozenset({'get', 'post', 'put', 'patch', 'delete'})


def _is_endpoint(node: ast.AST) -> bool:
    """A function routed by FastAPI: ``@router.get(...)`` and friends."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for decorator in node.decorator_list:
        func = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(func, ast.Attribute) and func.attr in _HTTP_METHODS:
            return True
    return False


def _takes_session(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    signature = ast.unparse(node.args)
    return any(hint in signature for hint in _SESSION_HINTS)


#: ``actor_user_id=current_user.id`` names who acted for the journal. It
#: says nothing about the organization -- the call may pass ``None`` for it
#: -- so it does not make ``current_user`` a carrier.
_JOURNAL_ACTOR = re.compile(r'actor_user_id=(?:current_user|user_context|ctx)\.id\b')


def _uses_a_carrier(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the body — not merely the signature — names a carrier.

    Declaring ``current_user`` and never using it is what an endpoint
    looks like when the scoping was forgotten, so the signature alone is
    not evidence.
    """
    body = '\n'.join(ast.unparse(statement) for statement in node.body)
    body = _JOURNAL_ACTOR.sub('', body)
    return any(carrier in body for carrier in _TENANT_CARRIERS)


@once_per_run
def collect_unscoped_endpoints(app_root: Path) -> dict[str, tuple[Path, int]]:
    """``{key: (file, line)}`` for endpoints with no carrier in the body."""
    found: dict[str, tuple[Path, int]] = {}
    for tree_name in ('api', 'modules'):
        root = app_root / tree_name
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob('*.py')):
            parts = _rel_parts(py_file, app_root)
            if _is_test_file(py_file, app_root) or '__pycache__' in parts:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding='utf-8'))
            except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
                continue
            for node in ast.walk(tree):
                if not _is_endpoint(node):
                    continue
                assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                if not _takes_session(node) or _uses_a_carrier(node):
                    continue
                found[f'{_rel(py_file)}::{node.name}'] = (py_file, node.lineno)
    return found


def _check_request_scope(app_root: Path, baseline: set[str] | None = None) -> list[str]:
    """Emit ``::error`` for a new endpoint that cannot scope its own work."""
    baseline = baseline or set()
    errors: list[str] = []
    for key, (py_file, line) in sorted(collect_unscoped_endpoints(app_root).items()):
        name = key.rsplit('::', 1)[1]
        severity = 'notice' if key in baseline else 'error'
        errors.append(
            f'::{severity} file={_rel(py_file)},line={line},'
            f'title=Architecture: endpoint without a tenant::'
            f'{name}() takes a database session and never touches the '
            f'organization — no require_org, no organization_id, not even '
            f'current_user passed on. Scope it, or add it to '
            f'app/core/request_scope_baseline.txt if it is global by '
            f'design (superuser, pre-login, public token).'
        )
    return errors
