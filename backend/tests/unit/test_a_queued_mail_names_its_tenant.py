"""A mail queued without an organization is a mail nobody can be shown.

The durable queue retries for about seven and a half minutes and then marks
the row ``failed``. The only way a human meets that row is through the
organization it belongs to, so a job queued with ``organization_id`` unset
ends its life in the container log — which is where an invitation, a
password-reset link and a registration link each went before this.

The facade requires the parameter, so omitting it raises — but every
module sends its mail best-effort, inside a ``try/except Exception`` that
logs a warning and carries on, because a notification must never break the
work it reports on. That swallows the TypeError too, and the notification
simply stops arriving. This gate is what makes the omission loud before it
ships, rather than in a log nobody reads.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_APP = Path(__file__).resolve().parents[2] / 'app'


def _is_facade_send(node: ast.Call) -> bool:
    """``core_api.email.send_async(...)`` — the one queue entry modules use."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in ('send_async', 'send_with_attachment_async')
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == 'email'
    )


def _sends_without_tenant() -> list[str]:
    offenders = []
    for path in _APP.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_facade_send(node):
                continue
            named = {kw.arg for kw in node.keywords}
            if 'organization_id' not in named:
                rel = path.relative_to(_APP.parent)
                offenders.append(f'{rel}:{node.lineno}')
    return offenders


def test_every_facade_send_names_its_organization() -> None:
    offenders = _sends_without_tenant()
    assert offenders == [], (
        'these mails are queued with no tenant, so no administrator can ever '
        'be shown that they failed: ' + ', '.join(offenders)
    )
