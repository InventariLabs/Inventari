"""Guardrail: a service, a core module or a vertical module never commits
and never rolls back.

One convention owns transactions in this codebase: services and core flush,
and the CALLER commits — for a request that is the request-scoped session
(``app/database.py::get_async_db``), which commits once, on success, before
the response is written. A ``db.commit()`` in the middle of the stack slices
the caller's unit of work in two (half of it can no longer be rolled back),
and a ``db.rollback()`` there erases everything the caller wrote before
asking — journal entries included. Both operations are gated.

The gate matches the OPERATION, not the receiver's variable name: any
``.commit()`` or ``.rollback()`` call in the scanned layers is a finding,
whatever the session happens to be called. Name-based matching was blind
twice over — ``sess = db; await sess.commit()`` renamed the receiver out of
sight, and legal owners with their own session (``ledger_db``, ``self._db``)
were invisible to it. Non-session objects do not commit in these layers;
when one appears, the finding is the right answer.

Explicit commits belong to transaction owners: the request dependency
itself, CLI entry points, seeds, and background jobs that hold no request
session. Those functions are listed in
``transaction_owner_allowlist.txt`` — a positive grant, not debt — and the
gate stays silent inside them, whatever the session is called and however
many times they commit.

Everything else that still commits or rolls back mid-stack rides a
baseline — ``transaction_ownership_baseline.txt`` for commits,
``transaction_rollback_baseline.txt`` for rollbacks — until its own
conversion wave. Baseline keys are per SITE, ``path::qualname@N``, where N
is the Nth such operation inside that function: a wave that removes a
commit removes exactly its line, and a second commit added to a baselined
function is a new, uncovered site — not a free rider on the old key.

Files under ``app/core/architecture_lint/`` are skipped — the gate reads
about commits more often than it makes them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ._constants import _is_test_file, _rel_parts
from ._run_cache import once_per_run

#: The two session operations only a transaction owner may perform.
_TRANSACTION_OPS = frozenset({'commit', 'rollback'})

_MESSAGES = {
    'commit': 'the caller owns the commit; flush and return.',
    'rollback': 'the caller owns the transaction; raise instead of rolling back.',
}


@dataclass(frozen=True)
class _TransactionSite:
    """One ``.commit()``/``.rollback()`` call, keyed so sites never merge.

    ``ordinal`` is the 1-based position of this operation among the same
    operations in the same function, so the key identifies the site, not
    the function: a function holding two commits owes two baseline lines.
    """

    rel_path: str
    qualname: str
    op: str
    ordinal: int
    lineno: int
    receiver: str

    @property
    def key(self) -> str:
        return f'{self.rel_path}::{self.qualname}@{self.ordinal}'

    @property
    def owner_key(self) -> str:
        """Function-level key, the shape the owner allowlist speaks."""
        return f'{self.rel_path}::{self.qualname}'


def _enclosing_qualname(tree: ast.AST, lineno: int) -> str:
    """The dotted name of the innermost function/class containing *lineno*.

    A key part, never a line number: a line number would shift with every
    edit above the call, and a key that moves is a key that stops covering
    what it promised.
    """
    best = ''
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not (node.lineno <= lineno <= getattr(node, 'end_lineno', node.lineno)):
            continue
        if isinstance(node, ast.ClassDef):
            best = f'{best}{node.name}.'
        else:
            best = f'{best}{node.name}'
    return best or '<module>'


@once_per_run
def _collect_transaction_sites(roots: list[Path]) -> list[_TransactionSite]:
    """Every ``.commit()``/``.rollback()`` call in the flush-only layers."""
    sites: list[_TransactionSite] = []
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob('*.py')):
            rel = _rel_parts(py_file, root)
            if _is_test_file(py_file, root) or '__pycache__' in rel:
                continue
            rel_path = '/'.join(rel)
            if 'architecture_lint' in rel:
                continue
            try:
                src = py_file.read_text(encoding='utf-8')
                tree = ast.parse(src)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            # The tree, not the text: a commit named in a docstring, a
            # comment or an error message is prose, not a transaction.
            calls: list[tuple[int, int, str, str]] = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (
                    not isinstance(func, ast.Attribute)
                    or func.attr not in _TRANSACTION_OPS
                ):
                    continue
                calls.append(
                    (node.lineno, node.col_offset, func.attr, ast.unparse(func.value))
                )
            calls.sort(key=lambda call: (call[0], call[1]))
            ordinals: dict[tuple[str, str], int] = {}
            for line_no, _col, op, receiver in calls:
                qualname = _enclosing_qualname(tree, line_no)
                ordinals[(qualname, op)] = ordinals.get((qualname, op), 0) + 1
                sites.append(
                    _TransactionSite(
                        rel_path=rel_path,
                        qualname=qualname,
                        op=op,
                        ordinal=ordinals[(qualname, op)],
                        lineno=line_no,
                        receiver=receiver,
                    )
                )
    return sites


def _check_transaction_ownership(
    roots: list[Path],
    *,
    commit_baseline: set[str] | None = None,
    rollback_baseline: set[str] | None = None,
    owner_allowlist: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Emit ``::error``/``::notice`` per mid-stack commit and rollback.

    Args:
        roots: the directories to scan (``app/services``, ``app/core``,
            ``app/modules``).
        commit_baseline: ``relative/path.py::qualname@N`` commit sites
            accepted for now.
        rollback_baseline: the same shape for rollbacks.
        owner_allowlist: function-level ``relative/path.py::qualname`` keys
            whose transactions are legal — background jobs, module routers
            holding their own session, seeds, CLI entry points, test
            helpers.

    Returns:
        tuple[list[str], list[str]]: GitHub-PR-formatted annotations,
        commits first, rollbacks second.
    """
    commit_base = commit_baseline or set()
    rollback_base = rollback_baseline or set()
    allow = owner_allowlist or set()
    commit_errors: list[str] = []
    rollback_errors: list[str] = []
    for site in _collect_transaction_sites(roots):
        if site.owner_key in allow:
            continue
        accepted = site.key in (commit_base if site.op == 'commit' else rollback_base)
        entry = (
            f'::{"notice" if accepted else "error"} '
            f'{site.rel_path}:{site.lineno}: '
            f'{site.receiver}.{site.op}() inside {site.qualname} — '
            f'{_MESSAGES[site.op]}'
        )
        (commit_errors if site.op == 'commit' else rollback_errors).append(entry)
    return commit_errors, rollback_errors
