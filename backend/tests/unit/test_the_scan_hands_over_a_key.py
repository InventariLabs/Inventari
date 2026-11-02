"""Gate: a scan answers with a catalogue key, not a sentence.

The label scan is the first screen a phone shows after somebody scans a code
in the warehouse, and the line under the status was built by the server as an
English sentence — ten of them, in a file that cannot know the language of
the person holding the phone. The status above that line was translated; the
line under it was not.

The rule here is mechanical, over every ``LabelScanResponse`` construction
site in ``app/`` — old, new, or a module's own provider (nutrition and
documents both ship one):

1. Nobody builds the response with a ``message``: there is no such field, and
   a sentence in any other field would put English on that screen again.
2. ``message_key`` is a namespaced catalogue key, not a phrase — the shape
   the check is about, not a list of the phrases that were there before.

The third half — that each of those keys actually resolves in all five
catalogues — lives on the side that owns the catalogues:
``frontend/src/i18n/scanServerKeys.test.ts`` reads these same construction
sites and resolves every literal key. It has to: a container running this
suite has no frontend tree to read, and a typo here reaches a phone as
``scan:result.labelReady`` — the raw key, under a translated status.
"""

import ast
import pathlib
import re

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'app'

#: ``ns:some.path`` — a namespace, a colon, then the key. No spaces, so a
#: sentence cannot pass as a key by accident.
KEY_SHAPE = re.compile(r'^[a-z_]+:[A-Za-z0-9_.]+$')


def _scan_response_calls() -> list[tuple[pathlib.Path, ast.Call]]:
    """Every ``LabelScanResponse(...)`` built in ``app/``, with its file.

    The three rules below are applied to the whole set, so a provider added
    later — in a module or in core — is covered without touching this file.
    """
    found: list[tuple[pathlib.Path, ast.Call]] = []
    for path in sorted(APP_ROOT.rglob('*.py')):
        if '/tests/' in str(path):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', '')
            if name == 'LabelScanResponse':
                found.append((path, node))
    return found


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword
    return None


class TestEveryScanAnswerIsAKey:
    def test_the_scan_response_grows_no_sentence_field(self) -> None:
        """The line is a key and its values; a sentence has no home here."""
        assert _scan_response_calls(), 'nie znaleziono żadnego LabelScanResponse'
        offenders = [
            f'{path.relative_to(APP_ROOT)}:{call.lineno}'
            for path, call in _scan_response_calls()
            if _keyword(call, 'message') is not None
        ]
        assert offenders == []

    def test_every_branch_hands_over_a_namespaced_key(self) -> None:
        """All of them, not only the one first measured."""
        missing: list[str] = []
        wrong_shape: list[str] = []
        for path, call in _scan_response_calls():
            where = f'{path.relative_to(APP_ROOT)}:{call.lineno}'
            keyword = _keyword(call, 'message_key')
            if keyword is None:
                missing.append(where)
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if not KEY_SHAPE.match(value.value):
                    wrong_shape.append(f'{where} → {value.value!r}')
        assert missing == []
        assert wrong_shape == []
