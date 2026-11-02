"""Guards for the two ways a 4xx envelope can silently degrade.

Both bugs these cover shipped to production and were invisible to the existing
suites, because every assertion on them checked only the status code.
"""

import ast
import pathlib

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException
from app.i18n import SUPPORTED_LANGUAGES
from app.i18n.service import get_error_message

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'app'


def _notfound_resource_args() -> list[tuple[str, int, str]]:
    """Every literal string passed as ``NotFoundException``'s first argument.

    Returns ``(relative_path, lineno, literal)``. Non-literal arguments (a
    variable, an f-string) are skipped — this check is about hardcoded values.
    """
    found: list[tuple[str, int, str]] = []
    for path in APP_ROOT.rglob('*.py'):
        if 'tests' in path.parts or 'migrations' in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, 'id', None) or getattr(func, 'attr', None)
            if name != 'NotFoundException':
                continue
            arg: ast.expr | None = None
            if node.args:
                arg = node.args[0]
            else:
                for kw in node.keywords:
                    if kw.arg == 'resource':
                        arg = kw.value
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(
                    (
                        str(path.relative_to(APP_ROOT.parent)),
                        node.lineno,
                        arg.value,
                    )
                )
    return found


class TestNotFoundResourceSlugs:
    """``NotFoundException(resource)`` takes a slug, never a human sentence.

    It builds the i18n key as ``f'{resource}_not_found'`` and the machine code
    as ``resource.upper() + '_NOT_FOUND'``. Passing a sentence produced live
    responses like::

        {'code': 'PURCHASE ORDER NOT FOUND_NOT_FOUND',
         'message': 'Purchase order not found_not_found'}

    — spaces inside a machine-readable code, and the key echoed back because
    ``i18n/service.py`` returns the key when it is missing.
    """

    def test_call_sites_pass_a_slug_not_a_sentence(self) -> None:
        offenders = [
            (path, line, literal)
            for path, line, literal in _notfound_resource_args()
            if literal != literal.lower() or not literal.replace('_', '').isalnum()
        ]
        assert offenders == [], (
            'NotFoundException must be given a lowercase snake_case slug '
            f'(got: {offenders})'
        )

    def test_every_slug_resolves_to_a_real_translation(self) -> None:
        unresolved = []
        for path, line, literal in _notfound_resource_args():
            key = f'{literal}_not_found'
            for lang in SUPPORTED_LANGUAGES:
                if get_error_message(key, lang) == key:
                    unresolved.append((path, line, key, lang))
        assert unresolved == [], (
            'missing i18n keys — the API would return the raw key as the '
            f'message: {unresolved}'
        )

    @pytest.mark.parametrize(
        'resource',
        ['purchase_order', 'reorder_rule', 'pricelist_entry', 'tax_rate'],
    )
    def test_regression_slugs_build_a_clean_envelope(self, resource: str) -> None:
        detail = NotFoundException(resource, 'pl').detail
        assert isinstance(detail, dict)
        assert detail['code'] == f'{resource.upper()}_NOT_FOUND'
        assert ' ' not in detail['code']
        assert not detail['message'].endswith('_not_found')


class TestRoleGuardEnvelope:
    """A role or permission guard must refuse with the structured 403 envelope,
    otherwise adopting a shared guard downgrades the response body."""

    def test_forbidden_exception_is_structured(self) -> None:
        detail = ForbiddenException(
            get_error_message('admin_permissions_required', 'en')
        ).detail
        assert detail == {
            'code': 'FORBIDDEN',
            'message': 'Admin permissions required for this action',
        }

    @pytest.mark.parametrize(
        'key',
        [
            'webhook_admin_only',
            'approvals_manage_admin_only',
            'approvals_action_admin_only',
            'documents_approve_requires_grant',
            'admin_permissions_required',
        ],
    )
    def test_guard_messages_are_translated_and_specific(self, key: str) -> None:
        generic = get_error_message('forbidden', 'en')
        for lang in SUPPORTED_LANGUAGES:
            message = get_error_message(key, lang)
            assert message != key, f'{key} missing for {lang}'
            assert message != generic, f'{key} degraded to the generic message'
