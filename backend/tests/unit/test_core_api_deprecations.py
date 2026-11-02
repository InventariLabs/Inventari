"""Tests for the core_api deprecation registry.

The events surface has had removal machinery since 0.9: every
deprecated alias carries a ``removal_release``, and a test fails the
build once that release ships. The core_api surface — a hundred times
larger — had only ``.. deprecated::`` docstrings with no deadline and
no guard. These tests give it the same two: the deadline is real, and
a deprecation written in a docstring must be registered to carry one.
"""

import ast
import inspect
import tomllib
from pathlib import Path

import pytest

from app.core import _core_api_deprecations, _event_deprecations
from app.core._core_api_deprecations import (
    DEPRECATED_CORE_API,
    deprecated_facade_chains,
)


def _backend_version() -> tuple[int, ...]:
    pyproject = Path(__file__).resolve().parents[2] / 'pyproject.toml'
    data = tomllib.loads(pyproject.read_text())
    return tuple(int(part) for part in data['project']['version'].split('.'))


def _public_api_root() -> Path:
    return Path(__file__).resolve().parents[2] / 'app' / 'core' / 'public_api'


def _deprecated_docstring_qualifiers() -> set[str]:
    """Every public_api method whose docstring declares a deprecation."""
    found: set[str] = set()
    for py_file in sorted(_public_api_root().rglob('*.py')):
        if '__pycache__' in str(py_file):
            continue
        tree = ast.parse(py_file.read_text(encoding='utf-8'))
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.ClassDef):
                continue
            for node in parent.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node) or ''
                    if 'deprecated::' in doc:
                        found.add(f'{parent.name}.{node.name}')
    return found


@pytest.mark.parametrize(
    'registry',
    [_core_api_deprecations, _event_deprecations],
    ids=['core_api', 'events'],
)
def test_a_fresh_deprecation_keeps_the_two_release_window(registry):
    """A deadline one minor release away removes a stable surface a release
    early: the window is N+2 (CONTRACTS_STABILITY.md §2)."""
    major, minor, *_ = _backend_version()
    default = tuple(int(p) for p in registry.REMOVAL_RELEASE.split('.'))
    assert default >= (major, minor + 2, 0), registry.REMOVAL_RELEASE


def test_no_removal_release_has_shipped_yet():
    """Fails when the removal release ships — clean up or bump expiry."""
    current = _backend_version()
    for qualifier, deprecation in DEPRECATED_CORE_API.items():
        removal = tuple(int(p) for p in deprecation.removal_release.split('.'))
        assert current < removal, (
            f'{qualifier}: removal release {deprecation.removal_release} reached '
            f'(platform is at {"".join(f"{p}." for p in current).rstrip(".")}) — '
            f'delete the deprecated surface or bump its expiry explicitly.'
        )


def test_the_surface_removed_without_a_window_did_not_come_back():
    """The qualifiers cut without a deprecation window are gone.

    Not merely unregistered — gone from the facade. Each had either no
    caller at all or callers in this tree only, so the deprecation window
    protected nobody and the removal cost three call sites. A re-added
    method would pass every other gate in this file (it has no docstring
    deadline to violate, and the registry it is missing from is the thing
    it is supposed to be missing from), so this is where it gets caught.
    """
    from app.core.public_api import core_api

    for namespace, method in (
        ('secrets', 'encrypt'),
        ('secrets', 'decrypt'),
        ('notifications', 'send_email_with_attachment_async'),
        ('stock', 'release_reservation_async'),
        ('users', 'promote_superuser'),
        ('users', 'get_by_id_async_full'),
        # The unscoped file-storage surface: every write it offered moved
        # under <org>/<module>/, so its return would reintroduce the
        # cross-tenant path it was removed for.
        ('file_storage', 'save'),
        ('file_storage', 'get'),
        ('file_storage', 'get_url'),
        ('file_storage', 'delete'),
        ('file_storage', 'exists'),
        # The quant table's own surface, gone with the table. A group of stock
        # is its records now: goods arrive and leave through the movement pass
        # (post_movement_async), a draw by strategy or on every shelf is the
        # records draw (take_from_the_records_async), and a pick line names a
        # group and a lot (find_best_pick_group_for_picking_async).
        ('stock', 'increment_quant_async'),
        ('stock', 'decrement_quant_async'),
        ('stock', 'decrement_quant_by_strategy_async'),
        ('stock', 'adjust_shelf_quantity_async'),
        ('stock', 'consume_across_locations_async'),
        ('stock', 'find_best_quant_for_picking_async'),
        ('stock', 'get_quant_by_id_async'),
        ('stock', 'get_pick_group_for_quant_async'),
        ('stock', 'quant_id_for_pick_group_async'),
        # The reservation that refused every call without a document. It
        # never reached a published release, so the window protected nobody.
        ('stock', 'reserve_async'),
        # The read-only card match a receipt line typed in words asked before
        # its record look-up. Receipts refuse such lines now, its one caller
        # went with them, and no published release ever carried it.
        ('product_templates', 'find_matching_async'),
    ):
        surface = getattr(core_api, namespace)
        assert not hasattr(surface, method), (
            f'core_api.{namespace}.{method} is back. It was removed '
            f'because it was unsafe or duplicated; if it is '
            f'genuinely needed, it needs a new name and a reason, not the '
            f'old one.'
        )
        assert f'{type(surface).__name__}.{method}' not in DEPRECATED_CORE_API


def test_every_registered_entry_carries_replacement_reason_and_deadline():
    for qualifier, deprecation in DEPRECATED_CORE_API.items():
        assert deprecation.replacement, qualifier
        assert deprecation.reason, qualifier
        assert deprecation.removal_release, qualifier


def test_every_deprecated_docstring_in_public_api_is_registered():
    """A deprecation without a registry entry is a promise with no
    deadline — the docstring says the surface is going away, and nothing
    ever checks whether it went. Write the registry entry (or fix the
    docstring) so the two tell the same story."""
    unregistered = _deprecated_docstring_qualifiers() - set(DEPRECATED_CORE_API)
    assert unregistered == set(), (
        f'deprecated:: docstrings without a registry entry: '
        f'{sorted(unregistered)} — add them to '
        f'app.core._core_api_deprecations with a removal_release'
    )


def test_registered_qualifiers_still_exist_in_public_api():
    """The registry points at surface that is deprecated but still
    present: a qualifier whose method no longer exists describes a
    ghost — remove the entry when the removal actually happens."""
    living: set[tuple[str, str]] = set()
    for py_file in sorted(_public_api_root().rglob('*.py')):
        if '__pycache__' in str(py_file):
            continue
        tree = ast.parse(py_file.read_text(encoding='utf-8'))
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.ClassDef):
                continue
            for node in parent.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    living.add((parent.name, node.name))
    for qualifier in DEPRECATED_CORE_API:
        class_name, method = qualifier.rsplit('.', 1)
        assert (class_name, method) in living, (
            f'{qualifier}: the method is gone from public_api — '
            f'remove the registry entry'
        )


#: Words that retire a method when they stand in the docstring's first
#: paragraph — the part that describes *this* method. Further down the same
#: words are ordinary prose about other things: ``decrypt_for_module``
#: explains two legacy *data shapes* it still reads, and
#: ``get_current_rate_async`` names a historical field label. Both must stay
#: sayable, so below the first paragraph only the phrases in
#: ``_RETIRING_PHRASES`` are refused.
_RETIRING_WORDS = (
    'legacy',
    'deprecated',
    'obsolete',
    'superseded',
    'will be removed',
    'no longer supported',
)

#: Phrases that say a method is going away. A bare word can describe a data
#: shape, a phrase of this form cannot: "is deprecated" and "will be removed"
#: are about the thing the sentence is the subject of. Read in every
#: paragraph, so a retirement written below the summary line does not escape.
_RETIRING_PHRASES = (
    'is deprecated',
    'are deprecated',
    'is obsolete',
    'is being removed',
    'will be removed',
    'to be removed',
    'will be retired',
    'superseded by',
    'no longer supported',
)

#: Where a retiring phrase is allowed to appear because the sentence is about
#: something other than the method. Empty by design: each entry is a method
#: qualifier mapped to the reason its prose is not a retirement.
_PROSE_EXEMPT: dict[str, str] = {}


def _summary_of(doc: str) -> str:
    """The docstring's first paragraph, lowercased."""
    return doc.strip().split('\n\n', 1)[0].lower()


def _prose_deprecations(root: Path | None = None) -> dict[str, list[str]]:
    """Methods whose docstring retires them without the token."""
    found: dict[str, list[str]] = {}
    for py_file in sorted((root or _public_api_root()).rglob('*.py')):
        if '__pycache__' in str(py_file):
            continue
        tree = ast.parse(py_file.read_text(encoding='utf-8'))
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.ClassDef):
                continue
            for node in parent.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                qualifier = f'{parent.name}.{node.name}'
                doc = ast.get_docstring(node) or ''
                if 'deprecated::' in doc or qualifier in _PROSE_EXEMPT:
                    continue
                words = [w for w in _RETIRING_WORDS if w in _summary_of(doc)]
                words += [
                    p for p in _RETIRING_PHRASES if p in doc.lower() and p not in words
                ]
                if words:
                    found[qualifier] = words
    return found


def test_a_deprecation_written_in_prose_does_not_pass_for_a_registered_one():
    """The registry guard matches a literal ``deprecated::``, so a
    retirement written in prose slipped past it *and* past the registry —
    silently, on a green gate.

    ``CoreStockAPI.release_reservation_async`` was exactly that: "(legacy
    API)" with "Prefer ``release_for_document_async``" underneath, no
    deadline, no entry, and a green build. A module author outside this
    repository had no way to learn the surface was going away.

    One spelling, then: a retirement is written with ``.. deprecated::``
    and registered with a date. Prose that retires a method in its own
    summary line, or says anywhere in the docstring that the method "will
    be removed" or "is deprecated", is refused here — the words stay sayable
    wherever the docstring is talking about something else.
    """
    prose = _prose_deprecations()
    assert prose == {}, (
        'these docstrings retire their own method without the token:\n'
        + '\n'.join(f'  - {q}: {words}' for q, words in sorted(prose.items()))
        + '\nWrite it as ".. deprecated:: <version>" and add the entry to '
        'app.core._core_api_deprecations, or reword the sentence.'
    )


def _write_surface(root: Path, docstring: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'probe.py').write_text(
        'class CoreProbeAPI:\n'
        '    async def fetch_async(self):\n'
        f'        """{docstring}"""\n'
    )


class TestTheGuardReadsTheWholeDocstring:
    """The summary-only reading let a retirement through when it was the
    second paragraph that said so."""

    def test_a_retirement_below_the_summary_line_is_named(self, tmp_path):
        _write_surface(
            tmp_path,
            'Fetch the probe.\n\n        This method is deprecated and will be '
            'removed in favour of fetch_v2_async.',
        )

        assert _prose_deprecations(tmp_path) == {
            'CoreProbeAPI.fetch_async': ['is deprecated', 'will be removed'],
        }

    def test_the_same_sentence_in_the_summary_line_is_still_named(self, tmp_path):
        _write_surface(tmp_path, 'Deprecated: use fetch_v2_async.')

        assert 'CoreProbeAPI.fetch_async' in _prose_deprecations(tmp_path)

    def test_a_bare_legacy_word_below_the_summary_is_not_a_retirement(self, tmp_path):
        _write_surface(
            tmp_path,
            'Read the probe.\n\n        Rows written before the rename still '
            'carry the legacy shape and are read as before.',
        )

        assert _prose_deprecations(tmp_path) == {}

    def test_the_token_is_the_registered_spelling_and_is_not_prose(self, tmp_path):
        _write_surface(
            tmp_path,
            'Fetch the probe.\n\n        .. deprecated:: 0.9\n'
            '           Will be removed in 1.0.',
        )

        assert _prose_deprecations(tmp_path) == {}

    def test_the_two_known_false_alarms_say_a_retiring_word_and_stay_green(self):
        """They are why the rule reads phrases below the summary rather than
        words: each carries a retiring word lower down, about data."""
        prose = _prose_deprecations()
        low = {}
        for name, qualifier in (
            ('secrets.py', 'decrypt_for_module'),
            ('valuation.py', 'get_current_rate_async'),
        ):
            source = (_public_api_root() / name).read_text(encoding='utf-8')
            tree = ast.parse(source)
            doc = next(
                (ast.get_docstring(n) or '')
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == qualifier
            )
            low[qualifier] = [w for w in _RETIRING_WORDS if w in doc.lower()]
            assert not any(q.endswith(qualifier) for q in prose), qualifier
        assert all(low.values()), low


# ---------------------------------------------------------------------------
# Deprecated methods warn at runtime, with the deadline
# ---------------------------------------------------------------------------


def _mocked_storage():
    """Patch FileStorageService construction so a warned call completes."""
    from io import BytesIO
    from unittest.mock import AsyncMock, MagicMock, patch

    service = MagicMock()
    service.save = AsyncMock()
    service.get = AsyncMock(return_value=BytesIO(b''))
    service.get_url = AsyncMock(return_value='https://example.test/url')
    service.delete = AsyncMock()
    service.exists = AsyncMock(return_value=True)
    return patch(
        'app.core.public_api.file_storage.FileStorageService',
        return_value=service,
    )


def _call_deprecated_save_for_org():
    """Call the synthetic entry's method, unawaited.

    The call is NOT awaited when the warning is recorded — the wrapper is
    synchronous on purpose, so it warns at the call site and hands the
    coroutine back for the caller to await exactly as before. The caller
    closes the coroutine; the mocked storage never runs.
    """
    from app.core.public_api import core_api

    return core_api.file_storage.save_for_org_async(
        '00000000-0000-0000-0000-000000000000', 'recipes', 'probe.bin', b'x'
    )


def _call_unawaited(chain: str):
    """Call a registered chain's method with placeholder arguments, unawaited.

    Every registered method is a coroutine function behind a synchronous
    wrapper: the call warns and hands back a coroutine whose body never
    runs, so ``None`` stands in for every argument it requires.
    """
    from app.core.public_api import core_api

    namespace, name = chain.split('.')
    method = getattr(getattr(core_api, namespace), name)
    args: list[None] = []
    kwargs: dict[str, None] = {}
    for parameter in inspect.signature(method).parameters.values():
        if parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[parameter.name] = None
        elif parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            args.append(None)
    return method(*args, **kwargs)


@pytest.fixture
def _synthetic_deprecation(monkeypatch):
    """Register a throwaway entry so the wrapper is measurable.

    A throwaway entry this file adds and takes back out, the pattern
    ``test_event_deprecations`` uses, measures the machinery whatever the
    register holds at the time. The qualifier names the scoped twin, which
    still exists: the wrapper skips an entry whose method is gone.

    The registry is read once at import, so an entry added later reaches
    the live facade only through ``install_runtime_warnings``; the
    instance attribute that call sets is removed again by this fixture's
    teardown. The call wraps every entry, so the ones the facade wrapped
    when it was built are put back as they were — wrapped once, not twice.
    """
    from app.core._core_api_deprecations import (
        CoreApiDeprecation,
        install_runtime_warnings,
    )
    from app.core.public_api import core_api

    wrapped_at_import = {
        chain: getattr(getattr(core_api, chain.split('.')[0]), chain.split('.')[1])
        for chain in deprecated_facade_chains()
    }
    monkeypatch.setitem(
        DEPRECATED_CORE_API,
        'CoreFileStorageAPI.save_for_org_async',
        CoreApiDeprecation(
            'CoreFileStorageAPI.save_for_org_async',
            'CoreFileStorageAPI.store_for_org',
            'test-only synthetic entry',
        ),
    )
    install_runtime_warnings(core_api)
    for chain, method in wrapped_at_import.items():
        namespace, name = chain.split('.')
        setattr(getattr(core_api, namespace), name, method)
    yield
    del core_api.file_storage.save_for_org_async


def test_every_registered_method_warns_at_runtime(_synthetic_deprecation):
    """The register drives the runtime: every entry warns, none is silent.

    Each chain is called through the facade it names, so an entry whose
    method this test never called would have passed unmeasured. The
    register holds only the synthetic entry here, and it warns.
    """
    chains = deprecated_facade_chains()
    assert chains, 'the synthetic entry did not reach the facade chain map'
    with _mocked_storage():
        for chain in chains:
            with pytest.warns(DeprecationWarning, match=f'core_api.{chain}'):
                coroutine = _call_unawaited(chain)
            coroutine.close()


def test_warning_names_the_deadline_and_the_replacement(_synthetic_deprecation):
    with _mocked_storage():
        with pytest.warns(DeprecationWarning) as recorded:
            coroutine = _call_deprecated_save_for_org()
        coroutine.close()

    message = str(recorded[0].message)
    assert '0.13.0' in message
    assert 'CoreFileStorageAPI.store_for_org' in message


def test_an_unregistered_method_does_not_warn(_synthetic_deprecation):
    """The register names methods one by one; a sibling stays silent."""
    import warnings as warnings_module

    from app.core.public_api import core_api

    with _mocked_storage():
        with warnings_module.catch_warnings():
            warnings_module.simplefilter('error')
            # Raises if an unregistered method warned — the register names
            # the synthetic chain alone, not the namespace it lives in.
            coroutine = core_api.file_storage.exists_for_org_async(
                '00000000-0000-0000-0000-000000000000', 'recipes', 'probe.bin'
            )
        coroutine.close()


def test_wrapper_is_invisible_to_the_method_snapshot(_synthetic_deprecation):
    """The wrapper lives on the instance; the class the snapshot gate reads
    still yields the recorded signatures."""
    import json

    from app.core.architecture_lint._constants import CORE_API_SNAPSHOT_FILE
    from app.core.architecture_lint._core_api_snapshot import (
        _signature_of,
        build_snapshot,
    )
    from app.core.public_api.file_storage import CoreFileStorageAPI

    recorded = json.loads(CORE_API_SNAPSHOT_FILE.read_text())['namespaces']

    live = build_snapshot()
    for ns_name, namespace in recorded.items():
        assert live['namespaces'][ns_name]['methods'] == namespace['methods'], (
            f'{ns_name}: the runtime wrapper leaked into what the snapshot gate reads'
        )
    # And the recorded shape itself is still the un-wrapped one: the
    # fixture's wrapper shadows the bound method on the facade instance,
    # never on the class read here.
    assert (
        _signature_of(CoreFileStorageAPI.save_for_org_async)
        == recorded['file_storage']['methods']['save_for_org_async']['params']
    )
