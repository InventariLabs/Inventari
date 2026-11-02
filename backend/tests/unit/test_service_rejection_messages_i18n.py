"""Gate: user-facing rejection messages must go through the i18n service.

Services raise ``ValueError`` for business-rule refusals and the global
handler in ``app.main`` maps every one of them to a 400 the client renders
as a toast. The envelope now translates only keyed rejections
(``ServiceRejectionError``) and stamps ``lang`` only there; a plain
``ValueError`` sentence reaches the reader untranslated. This gate makes
the rule mechanical instead of a promise:

1. **The rule, not a list.** Every ``raise ValueError('<sentence>')`` in
   ``app/`` is flagged — in any file, old or brand new — unless its literal
   sits in the ledger (``app/core/value_error_sentences_baseline.txt``). The ledger
   lives inside the directory the baseline ratchet scans, so appending a
   line is never enough to disarm the rule: growth fails the ratchet until
   it is consciously lowered (``manage.py arch lint
   --write-baseline-sizes``). The ledger is debt, not permission: a new
   client-facing refusal raises ``ServiceRejectionError('<key>')`` instead,
   and the generator (``manage.py arch lint --write-rejection-ledger``)
   rewrites entries from the same scan the gate runs, so the two cannot
   drift.
2. **The ledger carries no dead permits.** Every entry must match a live
   raise site; when a sentence is migrated or deleted, its lines become
   stale and this gate fails until they are pruned.
3. **Keys resolve.** Every i18n key handed to ``get_error_message``,
   ``*.translated`` or ``ServiceRejectionError`` anywhere in ``app/`` —
   not only at raise sites — must resolve in every shipped language (a
   community one through its English fallback);
   a missing translation fails here instead of reaching a reader's toast.
4. **The trade-flow surface stays key-shaped.** The historical strict layer
   over the PO / approvals / documents files (any exception type, no
   sentence-shaped literal at all) is kept on top of the global rule.

Allowed at a raise site: lowercase snake_case i18n keys and ALL_CAPS
machine codes. Anything else — a space, a mixed-case word — is a raw
English message waiting to leak into a toast. The historical denylist of
removed phrases is gone: every phrase on it was a ``ValueError`` sentence,
and the rule below refuses the *shape* in any file, which subsumes any
phrase list.
"""

import ast
import pathlib

from app.core.architecture_lint._quality_checks_rejections import (
    REFUSAL_LEDGER_FILE,
    REJECTION_LEDGER_FILE,
    is_key_or_code,
    keyed_dynamic_value_error_entries,
    ledger_entries,
    raw_refusal_sentence_entries,
    raw_value_error_sentence_entries,
)
from app.i18n import SUPPORTED_LANGUAGES
from app.i18n.service import get_error_message

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'app'
LEDGER_FILE = REJECTION_LEDGER_FILE

# Files whose ``raise`` sites surface messages to the user (routers wrap
# service errors into HTTP 4xx envelopes, or the global ValueError handler
# does). The global rule above covers every file; this set is the stricter
# shape check kept from the gate's first round, when it was the only
# defence of the trade-flow surface.
SCOPED_FILES: tuple[str, ...] = (
    'app/modules/purchase_orders/_router_approval.py',
    'app/modules/purchase_orders/_router_po.py',
    'app/modules/purchase_orders/_service_email.py',
    'app/modules/purchase_orders/_service_workflow.py',
    'app/modules/approvals/router.py',
    'app/modules/approvals/_services_request.py',
    'app/modules/approvals/_services_decisions.py',
    'app/modules/approvals/_services_workflow.py',
    'app/modules/warehouse/router.py',
    'app/modules/warehouse/_document_workflow_crud.py',
    'app/modules/warehouse/_document_workflow_transitions.py',
    'app/modules/approvals/_documents_router.py',
    'app/modules/approvals/document_gate.py',
    'app/schemas/partner.py',
)

LANGUAGES: tuple[str, ...] = SUPPORTED_LANGUAGES


def _app_trees() -> list[tuple[str, ast.AST]]:
    """Parse every non-test ``app/`` module once, as (repo-relative, tree)."""
    pairs: list[tuple[str, ast.AST]] = []
    for py_file in sorted(APP_ROOT.rglob('*.py')):
        if 'tests' in py_file.relative_to(APP_ROOT).parts:
            continue
        if '__pycache__' in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = py_file.relative_to(APP_ROOT.parent).as_posix()
        pairs.append((rel, tree))
    return pairs


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_400(call: ast.Call) -> bool:
    status = call.args[0] if call.args else _keyword(call, 'status_code')
    if isinstance(status, ast.Constant):
        return status.value == 400
    return isinstance(status, ast.Attribute) and status.attr == 'HTTP_400_BAD_REQUEST'


def _is_catalogue_lookup(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and getattr(node.func, 'id', getattr(node.func, 'attr', None))
        == 'get_error_message'
    )


def _catalogue_refusal_line() -> int:
    """Line of the one hand-built envelope, inside ``catalogue_refusal``."""
    source = (APP_ROOT / 'core' / 'exceptions.py').read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == 'catalogue_refusal':
            return next(
                inner.lineno
                for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and getattr(inner.func, 'id', None) == 'ValidationException'
            )
    raise AssertionError('catalogue_refusal is gone from app/core/exceptions.py')


_CATALOGUE_REFUSAL_LINE = _catalogue_refusal_line()


def _sentence_constants(exc: ast.expr) -> list[str]:
    """Sentence-shaped string literals inside one ``raise`` expression.

    Covers plain constants and the constant parts of f-strings, so
    ``raise ValueError(f'... {x} ...')`` is covered too.
    """
    return [
        child.value
        for child in ast.walk(exc)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and not is_key_or_code(child.value)
    ]


def _is_plain_value_error(exc: ast.expr) -> bool:
    """True when the raised exception is literally ``ValueError``.

    The global 400 handler maps ``ValueError`` itself (keyed rejections are
    the sanctioned alternative); subclasses carry their own routers or
    handlers and are out of this rule's scope.
    """
    target = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == 'ValueError'


def _ledger_entries() -> set[str]:
    """The ledger as the gate sees it — read through the scanner's own loader.

    The loader lives beside the generator (``_quality_checks_rejections``)
    on purpose: one module owns both halves of the file format, so a change
    to escaping cannot leave the gate reading what the generator no longer
    writes.
    """
    return ledger_entries(LEDGER_FILE)


class TestRawValueErrorSentences:
    def test_no_raw_value_error_sentence_outside_the_ledger(self) -> None:
        """A new raw sentence lights up without touching any list.

        The refusal contract: client-facing rejections raise
        ``ServiceRejectionError('<key>')``; a plain ``ValueError`` sentence
        is either an internal invariant (ledger, in a reachability group
        with a recorded mechanism) or migration pending (ledger, heading
        for a key). Appending a ledger line to silence a new site runs
        into the baseline ratchet — the count grows and the build stays
        red until the ratchet is consciously lowered.
        """
        ledger = _ledger_entries()
        assert ledger, 'ledger missing or empty — the rule lost its baseline'

        findings = raw_value_error_sentence_entries(APP_ROOT)
        fresh = sorted(findings - ledger)

        assert fresh == [], (
            f'{len(fresh)} raw ValueError sentence(s) outside the ledger — '
            'a client-facing refusal must raise ServiceRejectionError(key) so the '
            'envelope can translate it; a plain ValueError is for internal '
            'invariants only (see the ledger header): '
            f'{fresh[:10]}'
        )

    def test_the_ledger_holds_no_dead_permits(self) -> None:
        """Every ledger entry matches a live raise site.

        The mirror of the rule test: when a sentence is migrated to a key
        or deleted, its lines stop matching anything — open permits waiting
        for the next offender to hide behind. Prune them in the same change
        (and lower the ratchet, which will demand the same thing).
        """
        ledger = _ledger_entries()
        findings = raw_value_error_sentence_entries(APP_ROOT)

        stale = sorted(ledger - findings)

        assert stale == [], (
            f'{len(stale)} ledger line(s) no longer match any raise site — '
            f'prune them (and re-run arch lint --write-baseline-sizes): '
            f'{stale[:10]}'
        )

    def test_no_catalogue_message_is_raised_as_a_plain_value_error(self) -> None:
        """``ValueError(get_error_message(key, lang))`` answers without a code.

        The sentence is translated, but the envelope sees a plain
        ``ValueError`` and answers ``VALIDATION_ERROR``: the reason lives only
        in the words. ``ServiceRejectionError(key)`` carries the key, which the
        envelope turns into the ``code`` a client branches on. The scan is the
        one the ledger counts as "keyed-dynamic"; the rule is that it finds
        nothing.
        """
        keyed = keyed_dynamic_value_error_entries(APP_ROOT)

        assert not keyed, (
            'raise ServiceRejectionError(<key>, ...) instead of '
            f'ValueError(get_error_message(...)): {sorted(keyed)}'
        )

    def test_no_catalogue_message_is_wrapped_in_a_400_by_hand(self) -> None:
        """``ValidationException(get_error_message(key))`` answers without the key.

        Built by hand, the 400 carries the sentence and ``VALIDATION_ERROR``
        — or, as a raw ``HTTPException``, a bare string with no code at all.
        ``catalogue_refusal(key)`` (or ``ServiceRejectionError(key)``) answers
        with the key as the ``code``. The one place allowed to build the
        envelope by hand is ``catalogue_refusal`` itself.
        """
        by_hand: list[str] = []
        for rel, tree in _app_trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, 'id', getattr(node.func, 'attr', None))
                if name == 'ValidationException':
                    sentence = node.args[0] if node.args else _keyword(node, 'message')
                elif name == 'HTTPException' and _is_400(node):
                    sentence = _keyword(node, 'detail')
                else:
                    continue
                if _is_catalogue_lookup(sentence):
                    by_hand.append(f'{rel}:{node.lineno}')

        assert by_hand == ['app/core/exceptions.py:' + str(_CATALOGUE_REFUSAL_LINE)], (
            'raise catalogue_refusal(<key>, ...) instead of building the 400 '
            f'from get_error_message(...): {by_hand}'
        )

    def test_no_caught_refusal_is_answered_with_a_code_of_the_routers_choosing(
        self,
    ) -> None:
        """``ConflictException('X_CONFLICT', refusal_text(exc))`` drops the key.

        A router that maps a caught refusal to a 409 or a 413 chose one code
        for every reason the service can give: a taken partner code answered
        ``PARTNER_CONFLICT`` while the page of codes promised
        ``PARTNER_CODE_EXISTS``, and reopening an open period answered
        ``PERIOD_CLOSED`` beside a sentence saying it was not closed.
        ``refusal_code(exc, 'X_CONFLICT')`` answers with the refusal's own key
        and keeps the router's code only for a refusal that has none.
        """
        chosen: list[str] = []
        for rel, tree in _app_trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                values = [*node.args, *(k.value for k in node.keywords)]
                if not any(
                    isinstance(v, ast.Call)
                    and getattr(v.func, 'id', None) == 'refusal_text'
                    for v in values
                ):
                    continue
                if any(
                    isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                    and v.value.isupper()
                    for v in values
                ):
                    chosen.append(f'{rel}:{node.lineno}')

        assert chosen == [], (
            'answer a caught refusal with code=refusal_code(exc, <fallback>), '
            f"not a code of the router's own: {chosen}"
        )

    def test_every_rejection_key_resolves_in_all_languages(self) -> None:
        """Every key handed to the i18n helpers resolves in every shipped language.

        Collected from ALL call sites in ``app/`` — not only raise sites:
        messages are built outside raises too (401 fallbacks, email bodies,
        notification texts), and a key that resolves nowhere fails here
        instead of surfacing as raw snake_case wherever it is used.
        """
        keys: set[str] = set()
        for _rel, tree in _app_trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                is_get_error = (
                    isinstance(func, ast.Name) and func.id == 'get_error_message'
                )
                is_translated = (
                    isinstance(func, ast.Attribute) and func.attr == 'translated'
                )
                is_service_rejection = isinstance(func, ast.Name) and func.id in (
                    'ServiceRejectionError',
                    'catalogue_refusal',
                )
                if not (is_get_error or is_translated or is_service_rejection):
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)

        # Guards the collection itself: a rename that silently matches
        # nothing would turn this into a test that always passes.
        assert len(keys) >= 60, f'key collection matched too little: {keys}'

        unresolved: list[tuple[str, str]] = []
        for key in sorted(keys):
            for lang in LANGUAGES:
                if get_error_message(key, lang) == key:
                    unresolved.append((key, lang))
        assert unresolved == [], (
            'missing i18n translations — the API would return the raw key as '
            f'the message: {unresolved}'
        )


class TestTradeFlowSurfaceStaysKeyShaped:
    def test_no_sentences_at_raise_sites(self) -> None:
        """The strict historical layer: no sentence literal of any kind.

        The denylist only caught known phrases; a new bare
        ``raise ValueError('Something went wrong')`` sailed through. This
        shape check closes that gap for the trade-flow files: a literal
        with a space or mixed case is a raw message that would surface
        verbatim, whatever exception carries it.
        """
        trees = {rel: tree for rel, tree in _app_trees() if rel in SCOPED_FILES}
        missing = [rel for rel in SCOPED_FILES if rel not in trees]
        assert missing == [], f'scoped files vanished from the tree: {missing}'

        offenders: list[tuple[str, int, str]] = []
        for rel in SCOPED_FILES:
            for node in ast.walk(trees[rel]):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                for literal in _sentence_constants(node.exc):
                    offenders.append((rel, node.lineno, literal))
        assert offenders == [], (
            'raw message literals at raise sites — route them through '
            f'get_error_message()/ServiceRejectionError(key): {offenders}'
        )


class TestRefusalExceptionsCarryAKey:
    """The refusals the ValueError rule cannot see: HTTP and service-denial errors.

    The ValueError gate asks about ``raise ValueError('<sentence>')`` only. A
    router raising ``HTTPException(detail='<sentence>')`` or a service raising
    ``PeriodClosedError('<sentence>')`` reached the reader in English with no
    gate asking whether the refusal carried a translation key.
    """

    def test_no_refusal_sentence_outside_the_ledger(self) -> None:
        # Empty is the goal this ledger works towards; a missing file is what
        # would mean the rule lost its baseline.
        assert REFUSAL_LEDGER_FILE.exists(), 'refusal ledger missing'
        ledger = ledger_entries(REFUSAL_LEDGER_FILE)

        fresh = sorted(raw_refusal_sentence_entries(APP_ROOT) - ledger)

        assert fresh == [], (
            f'{len(fresh)} refusal sentence(s) outside the ledger — a refusal '
            'carries a translation key (get_error_message / ServiceRejectionError), '
            f'not an English sentence: {fresh[:10]}'
        )

    def test_the_refusal_ledger_holds_no_dead_permits(self) -> None:
        stale = sorted(
            ledger_entries(REFUSAL_LEDGER_FILE) - raw_refusal_sentence_entries(APP_ROOT)
        )

        assert stale == [], f'prune the ledger (--write-rejection-ledger): {stale[:10]}'

    def _scan(self, tmp_path: pathlib.Path, body: str) -> set[str]:
        target = tmp_path / 'app' / 'modules'
        target.mkdir(parents=True)
        (target / 'thing.py').write_text(body, encoding='utf-8')
        return raw_refusal_sentence_entries(tmp_path / 'app')

    def test_a_planted_http_exception_sentence_is_found(
        self, tmp_path: pathlib.Path
    ) -> None:
        found = self._scan(
            tmp_path,
            "raise HTTPException(status_code=409, detail='Period is closed.')\n",
        )

        assert found == {'app/modules/thing.py::Period is closed.'}

    def test_a_planted_service_denial_sentence_is_found(
        self, tmp_path: pathlib.Path
    ) -> None:
        found = self._scan(
            tmp_path,
            'class PeriodClosedError(ValueError):\n'
            '    pass\n\n'
            "raise PeriodClosedError('The period is already closed')\n",
        )

        assert found == {'app/modules/thing.py::The period is already closed'}

    def test_keys_codes_and_headers_pass(self, tmp_path: pathlib.Path) -> None:
        found = self._scan(
            tmp_path,
            "raise ConflictException('PERIOD_CLOSED', get_error_message('period_closed', lang))\n"
            "raise HTTPException(401, detail='invalid_token', headers={'WWW-Authenticate': 'Bearer'})\n",
        )

        assert found == set()

    def test_a_class_defined_in_the_planted_file_is_a_refusal(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The class graph, not a name list, decides what a refusal is."""
        found = self._scan(
            tmp_path,
            'class XyzRefusedError(ValueError):\n'
            '    pass\n\n'
            'class DeepRefusedError(XyzRefusedError):\n'
            '    pass\n\n'
            'class XyzHttpError(AppException):\n'
            '    pass\n\n'
            "raise XyzRefusedError('Unlisted A sentence')\n"
            "raise DeepRefusedError('Unlisted B sentence')\n"
            "raise XyzHttpError('Unlisted C sentence')\n",
        )

        assert found == {
            'app/modules/thing.py::Unlisted A sentence',
            'app/modules/thing.py::Unlisted B sentence',
            'app/modules/thing.py::Unlisted C sentence',
        }

    def test_plain_value_error_and_keyed_rejections_stay_out(
        self, tmp_path: pathlib.Path
    ) -> None:
        found = self._scan(
            tmp_path,
            'class KeyedError(ServiceRejectionError):\n'
            '    pass\n\n'
            'class Library(Exception):\n'
            '    pass\n\n'
            "raise ValueError('Own rule, not this one')\n"
            "raise KeyedError('Some sentence here')\n"
            "raise Library('Not a refusal class')\n",
        )

        assert found == set()
