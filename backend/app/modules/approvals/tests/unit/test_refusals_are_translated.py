"""Gate: the approvals engine refuses with catalogue keys, never sentences.

Every ``ApprovalError`` this module raises reaches a toast verbatim through
``str(exc)`` — in its own router and in the documents, purchase-order and
equipment proxies that re-raise the message. An English literal at a raise
site is therefore an English answer to a Polish reader, and it is easy to add
one without noticing: the code compiles, the tests pass, the sentence reads
fine to whoever wrote it.

So the rule is structural rather than a list of banned phrases: in the service
files below, an approvals exception is raised through ``.translated('key')``,
and the key resolves in every language (a community language through its
fallback to English) and is translated in the maintained ones. ``ApprovalNotFoundError`` is
exempt — routers turn it into ``NotFoundException``, which looks its own
message up by resource slug and never shows what the service passed.
"""

import ast
import pathlib

import pytest

from app.i18n import MAINTAINED_LANGUAGES, SUPPORTED_LANGUAGES
from app.i18n.service import get_error_message

MODULE_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Every service file in the module. Globbed rather than listed, so a new
# ``_services_*.py`` is covered the day it appears.
SERVICE_FILES: tuple[pathlib.Path, ...] = tuple(
    sorted(MODULE_ROOT.glob('_services_*.py'))
)

# Raised as-is: the router maps it to a 404 whose message comes from the
# resource slug, so the argument never reaches a reader.
EXEMPT: frozenset[str] = frozenset({'ApprovalNotFoundError'})

TRANSLATED_ERRORS: frozenset[str] = frozenset(
    {'ApprovalError', 'ApprovalRequiredError'}
)


def _raised_approval_errors(path: pathlib.Path) -> list[tuple[int, ast.Call]]:
    """Every ``raise <ApprovalError-ish>(...)`` call in one file."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found: list[tuple[int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        # ``ApprovalError(...)`` — the shape this gate rejects.
        if isinstance(func, ast.Name) and func.id in TRANSLATED_ERRORS | EXEMPT:
            found.append((node.lineno, node.exc))
        # ``ApprovalError.translated(...)`` — the shape it requires.
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in TRANSLATED_ERRORS | EXEMPT
        ):
            found.append((node.lineno, node.exc))
    return found


def _keys_in(path: pathlib.Path) -> list[str]:
    keys: list[str] = []
    for _lineno, call in _raised_approval_errors(path):
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr != 'translated':
            continue
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.append(first.value)
    return keys


class TestApprovalRefusalsAreTranslated:
    def test_the_gate_reads_some_files(self) -> None:
        """A glob that matches nothing would make every test below vacuous."""
        assert len(SERVICE_FILES) >= 5, [p.name for p in SERVICE_FILES]

    @pytest.mark.parametrize('path', SERVICE_FILES, ids=lambda p: p.name)
    def test_no_service_raises_a_bare_message(self, path: pathlib.Path) -> None:
        offenders: list[str] = []
        for lineno, call in _raised_approval_errors(path):
            func = call.func
            if isinstance(func, ast.Name):
                if func.id in EXEMPT:
                    continue
                offenders.append(f'{path.name}:{lineno} raise {func.id}(...)')
            elif isinstance(func, ast.Attribute) and func.attr != 'translated':
                offenders.append(f'{path.name}:{lineno} raise ...{func.attr}(...)')
        assert offenders == [], (
            'approvals refusals must carry a catalogue key — use '
            f'ApprovalError.translated("key"): {offenders}'
        )

    @pytest.mark.parametrize('path', SERVICE_FILES, ids=lambda p: p.name)
    def test_every_key_is_a_literal(self, path: pathlib.Path) -> None:
        """A computed key cannot be checked here, so it is not allowed."""
        computed: list[str] = []
        for lineno, call in _raised_approval_errors(path):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr != 'translated':
                continue
            first = call.args[0] if call.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                computed.append(f'{path.name}:{lineno}')
        assert computed == [], (
            f'the i18n key must be a literal so this gate can resolve it: {computed}'
        )

    def test_every_key_resolves_in_all_languages(self) -> None:
        unresolved: list[tuple[str, str]] = []
        keys = {key for path in SERVICE_FILES for key in _keys_in(path)}
        assert keys, 'no keys collected — the AST walk stopped matching'
        for key in sorted(keys):
            for lang in SUPPORTED_LANGUAGES:
                if get_error_message(key, lang) == key:
                    unresolved.append((key, lang))
        assert unresolved == [], (
            'missing translations — the API would answer with the raw key: '
            f'{unresolved}'
        )

    def test_translations_differ_from_english(self) -> None:
        """A copied English string resolves, and still speaks English.

        Held to the maintained languages: a community language that has not
        caught up answers in English by design.
        """
        untranslated: list[tuple[str, str]] = []
        keys = {key for path in SERVICE_FILES for key in _keys_in(path)}
        for key in sorted(keys):
            english = get_error_message(key, 'en')
            for lang in MAINTAINED_LANGUAGES:
                if lang == 'en':
                    continue
                if get_error_message(key, lang) == english:
                    untranslated.append((key, lang))
        assert untranslated == [], (
            f'these entries are still the English sentence: {untranslated}'
        )
