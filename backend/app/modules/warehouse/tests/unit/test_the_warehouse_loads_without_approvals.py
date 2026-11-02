"""The warehouse names approvals as an optional companion and loads without it.

It used to import the approvals module at module level in a dozen files and
call its gate itself, while its manifest required only items and locations:
documents could not load without the approvals package, and no other module
could gate a document the way approvals did. The gate is now a pre-post check
approvals registers. What the warehouse still says to approvals — how to
describe a document in its queue, what a document workflow would hold — it
says through imports made when approvals asks, never when the warehouse is
imported.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

_WAREHOUSE = Path(__file__).resolve().parents[2]


def _module_level_imports(tree: ast.Module) -> list[str]:
    """Every module a file imports when it is itself imported.

    Statements at the top level count, and so do those nested in a top-level
    ``if``/``try`` — except an ``if TYPE_CHECKING:`` block, which never runs.
    A function body runs when called, not on import.
    """
    found: list[str] = []

    def visit(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.append(node.module)
            elif isinstance(node, ast.If):
                if not (
                    isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING'
                ):
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)

    visit(tree.body)
    return found


@pytest.mark.unit
def test_no_warehouse_file_imports_approvals_when_it_is_imported() -> None:
    offenders = sorted(
        str(path.relative_to(_WAREHOUSE))
        for path in _WAREHOUSE.rglob('*.py')
        if 'tests' not in path.relative_to(_WAREHOUSE).parts
        and 'migrations' not in path.relative_to(_WAREHOUSE).parts
        and any(
            name == 'app.modules.approvals' or name.startswith('app.modules.approvals.')
            for name in _module_level_imports(
                ast.parse(path.read_text(encoding='utf-8'))
            )
        )
    )

    assert offenders == []


@pytest.mark.unit
def test_the_manifest_declares_approvals_optional() -> None:
    manifest = json.loads((_WAREHOUSE / 'manifest.json').read_text(encoding='utf-8'))

    assert 'approvals' in manifest['optional_requires']
    assert 'approvals' not in manifest['requires']
