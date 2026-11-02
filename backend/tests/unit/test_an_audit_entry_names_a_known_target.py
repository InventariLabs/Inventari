"""Every audit entry names a target type the enum knows.

``AuditTargetType`` exists because hand-typed literals spread across routers
are how the next one goes missing, and that is exactly what happened: two
values — an approval request and a production order — reached the log for
months without ever appearing in the enum, so the administrator's filter
offered them while no code could name them.

The check has to tell two identically-named arguments apart. ``target_type``
is also what an *approval request* is about (``'document'``,
``'purchase_order'``), governed by the approvals module's own list; only the
argument to ``log_action_async`` is governed by this enum. Reading the call
name rather than the keyword is the whole difference, and a grep cannot do
it — which is why this walks the syntax tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.contracts.dtos import AuditTargetType

pytestmark = pytest.mark.unit

_APP = Path(__file__).resolve().parents[2] / 'app'

#: The call whose ``target_type`` this enum governs, however it is reached —
#: directly, or through the CoreAPI facade modules must use.
_AUDIT_CALL = 'log_action_async'


def _literal_targets(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, value)`` for every audit call given a plain string target."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
        if name != _AUDIT_CALL:
            continue
        for keyword in node.keywords:
            if keyword.arg != 'target_type':
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                found.append((node.lineno, keyword.value.value))
    return found


def test_no_audit_call_invents_a_target_type() -> None:
    known = {member.value for member in AuditTargetType}
    unknown: list[str] = []

    for path in sorted(_APP.rglob('*.py')):
        if 'tests' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for line, value in _literal_targets(tree):
            if value not in known:
                unknown.append(f'{path.relative_to(_APP.parent)}:{line} → {value!r}')

    assert not unknown, (
        'These audit entries name a target type AuditTargetType does not know. '
        "Add the member — the administrator's filter is built from what the "
        'log contains, so an unknown value is offered and explains nothing:\n  '
        + '\n  '.join(unknown)
    )


class TestTheCheckItself:
    """The distinction it has to get right, stated as cases."""

    def test_reports_a_literal_the_enum_does_not_know(self) -> None:
        tree = ast.parse("log_action_async(db, target_type='wishlist')")

        assert _literal_targets(tree) == [(1, 'wishlist')]

    def test_ignores_the_approval_request_argument_of_the_same_name(self) -> None:
        # What an approval is *about* is a different vocabulary, and this
        # enum has no say in it.
        tree = ast.parse("request_approval(db, org, target_type='document')")

        assert _literal_targets(tree) == []

    def test_follows_the_call_through_the_coreapi_facade(self) -> None:
        tree = ast.parse(
            "core_api.audit_log.log_action_async(db, target_type='wishlist')"
        )

        assert _literal_targets(tree) == [(1, 'wishlist')]

    def test_says_nothing_about_a_target_type_that_is_not_a_literal(self) -> None:
        # An enum member, or a variable holding one, is what the rule wants;
        # it can only judge what it can read.
        tree = ast.parse('log_action_async(db, target_type=AuditTargetType.ITEM)')

        assert _literal_targets(tree) == []
