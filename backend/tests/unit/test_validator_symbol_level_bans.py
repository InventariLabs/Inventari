"""A ban naming a symbol must catch the ``from X import symbol`` form.

``FORBIDDEN_IMPORT_PREFIXES`` lists ``app.core.events.event_bus``, but the
validator only compared ``node.module`` — which for
``from app.core.events import event_bus`` is ``app.core.events``, so the ban
never fired. A community module could take the event bus directly and bypass
the CoreAPI facade the ban exists to enforce.
"""

from pathlib import Path
from pkgutil import resolve_name
from types import ModuleType

import pytest

from app.cli.module_validator import validate_safety
from app.core import module_safety
from app.core.module_validator import _find_safety_violations


def _assert_defining_module_is_banned(path: str) -> None:
    obj = resolve_name(path)
    if isinstance(obj, ModuleType):
        return
    defining_module = getattr(obj, '__module__', type(obj).__module__)
    if defining_module == 'builtins':
        # Banning the whole builtins module would also forbid safe functions.
        assert obj.__name__ in module_safety.FORBIDDEN_CALLS, path
        return
    assert defining_module.startswith(module_safety.FORBIDDEN_IMPORT_PREFIXES), (
        f'{path} is defined in {defining_module}, which needs an import ban'
    )


@pytest.mark.parametrize('path', module_safety.FORBIDDEN_IMPORT_PREFIXES)
def test_symbol_bans_cover_the_real_defining_module(path: str):
    _assert_defining_module_is_banned(path)


def test_symbol_ban_guard_detects_a_moved_definition(monkeypatch):
    bus = resolve_name('app.core.events.event_bus')
    monkeypatch.setattr(type(bus), '__module__', 'app.core.relocated_bus')

    with pytest.raises(AssertionError, match='app.core.relocated_bus'):
        _assert_defining_module_is_banned('app.core.events.event_bus')


@pytest.mark.parametrize('path', ['builtins.eval', 'builtins.exec'])
def test_builtin_symbol_bans_require_a_call_ban(monkeypatch, path: str):
    monkeypatch.setattr(module_safety, 'FORBIDDEN_CALLS', ())

    with pytest.raises(AssertionError, match=path):
        _assert_defining_module_is_banned(path)


def _module(tmp_path: Path, source: str, name: str = 'community_thing') -> Path:
    """A minimal module directory containing one file.

    The name decides the trust rule: an installed module reaches Core only
    through the declared surface, a shipped one keeps the wider ``app.`` reach
    the lint freezes for it.
    """
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'service.py').write_text(source)
    return module_dir


class TestSymbolLevelBan:
    def test_from_import_of_a_banned_symbol_is_caught(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'from app.core.events import event_bus\n')

        violations = _find_safety_violations(module_dir, [])

        assert violations, 'importing event_bus directly must be a violation'
        assert any('event_bus' in v for v in violations)

    @pytest.mark.parametrize(
        'source',
        [
            'from app.core._event_bus import event_bus\n',
            'from app.core import _event_bus\n',
            'import app.core._event_bus\n',
        ],
    )
    def test_the_reexported_origin_of_the_bus_is_caught(
        self, tmp_path: Path, source: str
    ):
        module_dir = _module(tmp_path, source)

        assert _find_safety_violations(module_dir, [])

    def test_the_facade_is_still_allowed(self, tmp_path: Path):
        """core_api is the supported path and must not be swept up."""
        module_dir = _module(tmp_path, 'from app.core.public_api import core_api\n')

        assert _find_safety_violations(module_dir, []) == []

    def test_sibling_symbols_from_the_same_module_are_allowed(self, tmp_path: Path):
        """Only event_bus is banned, not everything in app.core.events.

        An installed module cannot import the module at all — the declared
        surface is the SDK — so the symbol rule is exercised on a shipped one,
        where the ``app.`` path itself is allowed and only the bus is not.
        """
        module_dir = _module(
            tmp_path, 'from app.core.events import emit_safe\n', name='warehouse'
        )

        assert _find_safety_violations(module_dir, []) == []


# Every case below must be judged identically by both entry points. The CLI gate
# runs *before* installation and the registry gate at load; a module the CLI
# waves through and the registry then rejects means the earlier, cheaper check
# was the weaker one — which is how the symbol-level ban above went missing from
# the CLI copy for as long as the two scanners were separate code.
PARITY_CASES = [
    pytest.param('from app.core.events import event_bus\n', True, id='banned-symbol'),
    pytest.param('from app.core._event_bus import event_bus\n', True, id='bus-origin'),
    pytest.param('from app.models.item import Item\n', True, id='banned-module'),
    pytest.param('import subprocess\n', True, id='banned-toplevel'),
    pytest.param('eval("2 + 2")\n', True, id='forbidden-call'),
    pytest.param('import requests\n', True, id='undeclared-capability'),
    pytest.param('open("f")\n', True, id='undeclared-filesystem'),
    pytest.param('from app.core.public_api import core_api\n', False, id='facade'),
    pytest.param('from app.core.events import emit_safe\n', True, id='outside-surface'),
    pytest.param('x = 1\n', False, id='clean'),
]


class TestBothGatesAgree:
    @pytest.mark.parametrize(('source', 'is_violation'), PARITY_CASES)
    def test_registry_and_cli_reach_the_same_verdict(
        self, tmp_path: Path, source: str, is_violation: bool
    ):
        module_dir = _module(tmp_path, source)

        registry = _find_safety_violations(module_dir, [])
        cli = validate_safety(module_dir, [])

        assert bool(registry) is is_violation
        assert len(cli) == len(registry), (
            f'gates disagree on {source!r}: registry={registry}, cli={cli}'
        )

    def test_the_cli_gate_catches_the_banned_symbol_too(self, tmp_path: Path):
        """The regression that motivated the merge, pinned on the CLI side."""
        module_dir = _module(tmp_path, 'from app.core.events import event_bus\n')

        errors = validate_safety(module_dir, [])

        assert any('event_bus' in e for e in errors)
        assert all(e.startswith('community_thing: ') for e in errors)

    def test_an_unparsable_file_is_a_finding_not_a_crash(self, tmp_path: Path):
        """The CLI copy used to let a bad encoding abort the whole run."""
        module_dir = tmp_path / 'community_thing'
        module_dir.mkdir()
        (module_dir / 'broken.py').write_bytes(b'def f(:\n')

        assert any('cannot parse' in e for e in validate_safety(module_dir, []))
        assert any('Cannot parse' in v for v in _find_safety_violations(module_dir, []))


@pytest.mark.parametrize(
    'source',
    [
        'from ...models.item import Item\n',
        'from ...database import get_db\n',
        'from ... import database\n',
    ],
)
def test_relative_import_cannot_climb_past_a_path_ban(tmp_path: Path, source: str):
    module_dir = tmp_path / 'community_thing'
    module_dir.mkdir()
    (module_dir / 'service.py').write_text(source)
    assert _find_safety_violations(module_dir, [])
    assert validate_safety(module_dir, [])


def test_relative_import_inside_the_module_is_not_flagged(tmp_path: Path):
    module_dir = tmp_path / 'community_thing'
    (module_dir / 'sub').mkdir(parents=True)
    (module_dir / 'sub' / 'a.py').write_text(
        'from ..service import X\nfrom . import b\n'
    )
    assert _find_safety_violations(module_dir, []) == []
