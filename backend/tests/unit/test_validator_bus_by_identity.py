"""The event bus is banned as an object, not as the paths that lead to it.

The import ban names ``app.core.events.event_bus`` and ``app.core._event_bus``,
but every app module that imports the bus for its own use holds it at module
level, and its namespace hands it out: ``from app.core.public_api.events
import event_bus`` took the raw singleton past the facade's checks while the
path list saw an allowed import. A list of paths cannot keep up with every
module that happens to import the bus, so the scan resolves the names an
untrusted module reaches under ``app.`` and compares what they are.
"""

import importlib
import pkgutil
import signal
import sys
from pathlib import Path

import pytest

import app
from app.cli.module_validator import validate_safety
from app.core._event_bus import event_bus
from app.core.module_safety_analysis import analyze_module_safety
from app.core.module_validator import _find_safety_violations


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('INVENTARI_VALIDATION_CACHE_DIR', str(tmp_path / 'cache'))


def _module(tmp_path: Path, source: str, name: str = 'community_thing') -> Path:
    """A minimal untrusted module directory containing one file."""
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'service.py').write_text(source)
    return module_dir


BUS_PATHS = [
    pytest.param(
        'from app.core.public_api.events import event_bus\n', id='public-facade'
    ),
    pytest.param('from app.core.outbox_relay import event_bus\n', id='outbox-relay'),
    pytest.param(
        'from app.core.public_api.events import event_bus as bus\n', id='aliased'
    ),
    pytest.param(
        'import app.core.events as ev\nev.event_bus.emit("x", {})\n',
        id='attribute-on-aliased-module',
    ),
    pytest.param(
        'from app.core import events\nevents.event_bus\n',
        id='attribute-on-from-imported-module',
    ),
    pytest.param(
        'import app.core.public_api.events\napp.core.public_api.events.event_bus\n',
        id='attribute-on-dotted-import',
    ),
    pytest.param('from app.core.events import *\n', id='star-import'),
    pytest.param('from ...core.outbox_relay import event_bus\n', id='relative'),
]


class TestTheBusIsCaughtWhereverItIsReached:
    @pytest.mark.parametrize('source', BUS_PATHS)
    def test_the_registry_gate_refuses_it(self, tmp_path: Path, source: str):
        violations = _find_safety_violations(_module(tmp_path, source), [])

        assert any('event_bus' in v for v in violations), violations

    @pytest.mark.parametrize('source', BUS_PATHS)
    def test_the_cli_gate_refuses_it(self, tmp_path: Path, source: str):
        errors = validate_safety(_module(tmp_path, source), [])

        assert any('event_bus' in e for e in errors), errors

    @pytest.mark.parametrize('source', BUS_PATHS)
    def test_a_cached_verdict_still_refuses_it(self, tmp_path: Path, source: str):
        """The cache keys on the module's files; what an app name resolves to
        is decided fresh, so a verdict cached before a core module started
        exposing the bus cannot answer for it afterwards."""
        module_dir = _module(tmp_path, source)
        analyze_module_safety(module_dir, [])

        assert any(
            'event_bus' in f.subject for f in analyze_module_safety(module_dir, [])
        )

    def test_one_reach_is_one_finding(self, tmp_path: Path):
        """The path ban and the identity check must not both report the
        same statement, nor a chain once per link.

        On `vision`: shipped, so the declared surface does not apply, and not
        on the trusted list, so the path ban and the identity check both still
        do. An installed module cannot import ``app.core.events`` at all any
        more — the surface refuses the path before the bus rule is reached.
        """
        module_dir = _module(
            tmp_path,
            'from app.core.events import event_bus\n'
            'import app.core.events as ev\n'
            'ev.event_bus.emit("x", {})\n',
            name='vision',
        )

        lines = sorted(f.lineno for f in analyze_module_safety(module_dir, []))

        assert lines == [1, 3]


DYNAMIC_READS = [
    pytest.param(
        "from app.core import events\nx = vars(events)['event_bus']\n", id='vars'
    ),
    pytest.param(
        "from app.core import events\nx = events.__dict__['event_bus']\n",
        id='dunder-dict',
    ),
    pytest.param(
        'from app.core import events\nm = [events]\nm[0].event_bus\n',
        id='container',
    ),
    pytest.param(
        'from app.core import events\nname = "event_" + "bus"\n'
        'x = getattr(events, name)\n',
        id='non-literal-getattr',
    ),
    pytest.param(
        "import app.core.events\nx = vars(app.core.events)['event_bus']\n",
        id='vars-of-dotted-chain',
    ),
    pytest.param(
        'import app.core.events\nm = [app.core.events]\nx = m[0].event_bus\n',
        id='container-of-dotted-chain',
    ),
    pytest.param(
        'from app.core import events\nclass Box: pass\nbox = Box()\n'
        "box.e = events\nx = vars(box.e)['event_bus']\n",
        id='stored-on-an-attribute',
    ),
    pytest.param(
        "from app.core import events\nx = getattr(events, '__dict__')['event_bus']\n",
        id='literal-getattr-of-dunder-dict',
    ),
    pytest.param(
        'import app.core.events\n'
        "events = getattr(app.core, 'events')\nx = vars(events)['event_bus']\n",
        id='module-from-literal-getattr-aliased',
    ),
    pytest.param(
        "import app.core.events\nx = vars(getattr(app.core, 'events'))['event_bus']\n",
        id='module-from-literal-getattr-in-vars',
    ),
    pytest.param(
        "import app.core.events\nx = getattr(app.core, 'events').__dict__['event_bus']\n",
        id='module-from-literal-getattr-dunder-dict',
    ),
    pytest.param(
        "from app.core import events\nx = events.__getattribute__('event_bus')\n",
        id='module-getattribute-accessor',
    ),
    pytest.param(
        'from app.core import events\n'
        "x = getattr(events, '__getattribute__')('event_bus')\n",
        id='module-literal-getattr-of-getattribute',
    ),
    pytest.param(
        "import app.core.events\nevents = vars(app.core)['events']\n"
        "x = vars(events)['event_bus']\n",
        id='parent-namespace-then-submodule',
    ),
    pytest.param(
        'import app.core.events\n'
        "x = app.core.__dict__['events'].__dict__['event_bus']\n",
        id='parent-dunder-dict-chained',
    ),
    pytest.param(
        "import app.core.events\nname = 'ev' + 'ents'\n"
        "events = getattr(app.core, name)\nx = vars(events)['event_bus']\n",
        id='parent-non-literal-getattr',
    ),
    pytest.param(
        "from app.core import public_api\nevents = vars(public_api)['events']\n"
        "x = vars(events)['event_bus']\n",
        id='unexported-submodule-vars',
    ),
    pytest.param(
        'from app.core import public_api\n'
        "x = public_api.__dict__['events'].__dict__['event_bus']\n",
        id='unexported-submodule-dunder-dict',
    ),
    pytest.param(
        "from app.core import public_api\nname = 'ev' + 'ents'\n"
        "events = getattr(public_api, name)\nx = vars(events)['event_bus']\n",
        id='unexported-submodule-non-literal-getattr',
    ),
    pytest.param(
        "from app.core import events\nx = globals()['events'].__dict__['event_bus']\n",
        id='globals-subscript',
    ),
    pytest.param(
        "from app.core import events\nx = vars(locals()['events'])['event_bus']\n",
        id='locals-subscript',
    ),
    pytest.param(
        'from app.core import events\nalias = events\n'
        "x = vars(globals()['alias'])['event_bus']\n",
        id='globals-alias',
    ),
]


class TestDynamicNamespaceReadsAreRefused:
    @pytest.mark.parametrize('source', DYNAMIC_READS)
    def test_the_registry_gate_refuses_it(self, tmp_path: Path, source: str):
        violations = _find_safety_violations(_module(tmp_path, source), [])

        assert any('event_bus' in v for v in violations), violations

    @pytest.mark.parametrize('source', DYNAMIC_READS)
    def test_the_cli_gate_refuses_it(self, tmp_path: Path, source: str):
        errors = validate_safety(_module(tmp_path, source), [])

        assert any('event_bus' in e for e in errors), errors

    def test_a_star_import_exposes_only_the_exports(self, tmp_path: Path):
        source = 'from app.core.public_api import *\n'

        assert _find_safety_violations(_module(tmp_path, source), []) == []

    def test_a_module_without_the_bus_may_be_passed_around(self, tmp_path: Path):
        """Shipped, so the surface lifts; not trusted, so the bus rule applies."""
        source = 'from app.core import cursor\nm = [cursor]\nvars(cursor)\n'

        assert (
            _find_safety_violations(_module(tmp_path, source, name='vision'), []) == []
        )


class TestTheBusClassIsCaughtToo:
    @pytest.mark.parametrize(
        'source',
        [
            'from app.core.context import EventBus\n',
            'import app.core.context as c\nc.EventBus()\n',
        ],
    )
    def test_a_module_may_not_build_its_own_bus(self, tmp_path: Path, source: str):
        violations = _find_safety_violations(_module(tmp_path, source), [])

        assert any('EventBus' in v for v in violations), violations


class TestWhatStaysAllowed:
    @pytest.mark.parametrize(
        'source',
        [
            'from app.core.public_api import core_api\n',
            'from app.core.public_api.events import EventValidationError\n',
            'import app.core.events as ev\nev.emit_safe\n',
            'from app.core.events import emit_safe\n',
            'import app.core.no_such_module as nope\nnope.event_bus\n',
            'event_bus = None\nevent_bus.emit\n',
        ],
    )
    def test_the_rest_of_the_namespace_is_untouched(self, tmp_path: Path, source: str):
        # vision is shipped (the surface lifts) and not trusted (the bus
        # rules still apply); an installed module cannot import
        # app.core.events at all, so the rule could not be read there.
        assert (
            _find_safety_violations(_module(tmp_path, source, name='vision'), []) == []
        )

    def test_a_trusted_shipped_module_may_still_hold_the_bus(self, tmp_path: Path):
        module_dir = _module(
            tmp_path,
            'from app.core.public_api.events import event_bus\n',
            name='recipes',
        )

        assert _find_safety_violations(module_dir, []) == []

    def test_resolution_does_not_import_an_unshipped_module(self, tmp_path: Path):
        """Resolving a name must not execute code the scan is there to judge."""
        module_dir = _module(
            tmp_path, 'from app.modules.community_thing.service import event_bus\n'
        )
        (module_dir / '__init__.py').write_text('raise RuntimeError("executed")\n')

        _find_safety_violations(module_dir, [])

        assert 'app.modules.community_thing' not in sys.modules


def _bus_exposures() -> list[tuple[str, str]]:
    """Every ``(module, name)`` under ``app.`` whose namespace holds the bus.

    Every module is imported, not only what the app happens to have loaded:
    a module nobody imported yet is still a door the scan resolves on demand.
    """
    for info in pkgutil.walk_packages(app.__path__, 'app.'):
        if '.tests' not in info.name and '.migrations' not in info.name:
            importlib.import_module(info.name)
    return sorted(
        (module_name, attr)
        for module_name, module in list(sys.modules.items())
        if module_name.startswith('app.') and module is not None
        for attr, value in list(vars(module).items())
        if value is event_bus
    )


class TestEveryExposureIsCovered:
    """A new app module that imports the bus becomes one more door; this
    fails the day such a door opens without the scan seeing it."""

    def test_the_enumeration_sees_the_known_doors(self):
        exposures = _bus_exposures()

        assert ('app.core.public_api.events', 'event_bus') in exposures
        assert ('app.core.outbox_relay', 'event_bus') in exposures
        assert (
            'app.services.storage._writes',
            'event_bus',
        ) in exposures

    def test_every_exposure_is_refused_by_both_gates(self, tmp_path: Path):
        module_dir = tmp_path / 'community_thing'
        module_dir.mkdir()
        exposures = _bus_exposures()
        for i, (module_name, attr) in enumerate(exposures):
            (module_dir / f'from_{i}.py').write_text(
                f'from {module_name} import {attr}\n'
            )
            (module_dir / f'attr_{i}.py').write_text(
                f'import {module_name} as m\nm.{attr}\n'
            )

        findings = analyze_module_safety(module_dir, [], use_cache=False)
        flagged = {f.rel_path.name for f in findings}
        missed = [
            (module_name, attr, shape)
            for i, (module_name, attr) in enumerate(exposures)
            for shape in ('from', 'attr')
            if f'{shape}_{i}.py' not in flagged
        ]

        assert not missed, f'the scan lets the bus through: {missed}'
        assert len(_find_safety_violations(module_dir, [])) == len(
            validate_safety(module_dir, [])
        )


class TestTheBusIsCaughtWhenTheModuleIsHandedOn:
    @pytest.mark.parametrize(
        'source',
        [
            pytest.param(
                'from app.core import events\ne = events\nx = e.event_bus\n',
                id='assignment-alias',
            ),
            pytest.param(
                'from app.core import events\na = events\nb = a\nb.event_bus\n',
                id='alias-of-an-alias',
            ),
            pytest.param(
                'from app.core import events\ngetattr(events, "event_bus")\n',
                id='getattr-with-a-literal',
            ),
            pytest.param(
                'import importlib\n'
                'importlib.import_module("app.core.events").event_bus\n',
                id='import-module',
            ),
            pytest.param(
                'from app.core import events, logging\n'
                'e = logging\ne = events\nvalue = e.event_bus\n',
                id='alias-reassigned-to-the-module',
            ),
            pytest.param(
                'from app.core import events\n'
                'def harmless():\n    events = None\n'
                'def unsafe():\n    return events.event_bus\n'
                'x = unsafe()\n',
                id='local-rebind-in-another-function-does-not-hide-it',
            ),
            pytest.param(
                'from app.core import events\ne = events; x = e.event_bus; e = None\n',
                id='read-before-the-rebind-on-the-same-line',
            ),
            pytest.param(
                'from app.core import events\nif False:\n    events = None\n'
                'x = events.event_bus\n',
                id='rebind-under-a-branch-does-not-hide-the-import',
            ),
            pytest.param(
                'from app.core import events\ne = events\nfor _ in []:\n    e = None\n'
                'x = e.event_bus\n',
                id='rebind-in-a-loop-does-not-hide-the-alias',
            ),
            pytest.param(
                'from app.core import events\nclass Harmless:\n    events = None\n'
                'x = events.event_bus\n',
                id='class-attribute-does-not-hide-the-import',
            ),
            pytest.param(
                'from app.core import events\nfrom contextlib import suppress\n'
                'with suppress(ValueError):\n    raise ValueError()\n    events = None\n'
                'x = events.event_bus\n',
                id='rebind-a-suppressing-with-skips-does-not-hide-the-import',
            ),
            pytest.param(
                'from app.core import events\nevents = None\n'
                'from app.core import events\nx = events.event_bus\n',
                id='a-later-import-takes-the-name-back',
            ),
        ],
    )
    def test_the_gate_refuses_it(self, tmp_path: Path, source: str):
        assert _find_safety_violations(_module(tmp_path, source), [])

    def test_an_alias_of_a_harmless_name_stays_allowed(self, tmp_path: Path):
        source = 'from app.core import events\ne = events\ne.emit_safe\n'

        assert (
            _find_safety_violations(_module(tmp_path, source, name='vision'), []) == []
        )

    def test_reusing_a_module_alias_name_is_conservatively_refused(
        self, tmp_path: Path
    ):
        source = (
            'from app.core import events\n'
            'from types import SimpleNamespace\n'
            'e = events\n'
            'e = SimpleNamespace(event_bus=None)\n'
            'value = e.event_bus\n'
        )

        assert _find_safety_violations(_module(tmp_path, source), [])

    def test_an_alias_in_any_scope_is_conservatively_refused(self, tmp_path: Path):
        source = (
            'from app.core import events\n'
            'from types import SimpleNamespace\n'
            'e = SimpleNamespace(event_bus=None)\n'
            'def unused():\n    e = events\n'
            'x = e.event_bus\n'
        )

        assert _find_safety_violations(_module(tmp_path, source), [])

    def test_class_alias_names_are_conservatively_refused(self, tmp_path: Path):
        source = (
            'from app.core import events\n'
            'from types import SimpleNamespace\n'
            'e = SimpleNamespace(event_bus=None)\n'
            'class H:\n    e = events\n'
            '    def read(self):\n        return e.event_bus\n'
        )

        assert _find_safety_violations(_module(tmp_path, source), [])

    @pytest.mark.parametrize(
        'source',
        [
            pytest.param(
                'from app.core import events\ne = events\n'
                'def read(e):\n    return e.event_bus\n',
                id='a-parameter',
            ),
            pytest.param(
                'from app.core import events\ne = events\n'
                'def e():\n    pass\ne.event_bus = None\nx = e.event_bus\n',
                id='a-def',
            ),
            pytest.param(
                'from app.core import events\ne = events\n'
                'class e:\n    event_bus = None\nx = e.event_bus\n',
                id='a-class',
            ),
            pytest.param(
                'from app.core import events\ne = events\n'
                'e, f = 1, 2\nx = e.event_bus\n',
                id='an-unpacking',
            ),
        ],
    )
    def test_other_bindings_cannot_erase_a_possible_module(
        self, tmp_path: Path, source: str
    ):
        assert _find_safety_violations(_module(tmp_path, source), [])


class TestBindingsCannotEraseAReachableModule:
    def test_a_shared_alias_graph_finishes_within_the_scan_budget(self, tmp_path: Path):
        """Repeated reads must not enumerate every route through a diamond DAG."""
        source = 'from app.core import events\n'
        for i in range(32):
            source += f'x{i} = x{i + 1}\nx{i} = x{i + 2}\n'
        source += 'x32 = events\nx33 = events\n'
        source += 'x0.event_bus\n' * 40
        module_dir = _module(tmp_path, source)

        def exceeded_budget(signum, frame):
            raise AssertionError('alias resolution exceeded ten seconds')

        previous = signal.signal(signal.SIGALRM, exceeded_budget)
        signal.setitimer(signal.ITIMER_REAL, 10)
        try:
            assert any(
                'event_bus' in v for v in _find_safety_violations(module_dir, [])
            )
            assert any('event_bus' in e for e in validate_safety(module_dir, []))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    @pytest.mark.parametrize(
        'source',
        [
            pytest.param(
                'from app.core import events\nevents: object\nx = events.event_bus\n',
                id='annotation-only',
            ),
            pytest.param(
                'from app.core import events\n'
                'events: object = events\n'
                'x = events.event_bus\n',
                id='annotated-rebind',
            ),
            pytest.param(
                'from app.core import events\n'
                '[0 for events in range(1)]\n'
                'x = events.event_bus\n',
                id='comprehension',
            ),
            pytest.param(
                'from app.core import events\n'
                'list(0 for events in range(1))\n'
                'x = events.event_bus\n',
                id='generator',
            ),
            pytest.param(
                'from app.core import events\n'
                'y = events\n'
                'events = None\n'
                'for i in range(2):\n'
                '    x = events.event_bus if i else 0\n'
                '    events = y\n',
                id='loop-back-edge',
            ),
            pytest.param(
                'from app.core import events\n'
                'def read():\n'
                '    e = outer\n'
                '    return e.event_bus\n'
                'outer = events\n'
                'x = read()\n',
                id='later-outer-alias',
            ),
            pytest.param(
                'from app.core import events\n'
                'def bind():\n'
                '    global e\n'
                '    e = events\n'
                'bind()\n'
                'x = e.event_bus\n',
                id='global-alias',
            ),
            pytest.param(
                'from app.core import events as e\n'
                'from types import SimpleNamespace as e\n'
                'x = e.event_bus\n',
                id='reused-import-name',
            ),
            pytest.param(
                'from app.core import events\ne: object = events\nx = e.event_bus\n',
                id='annotated-alias',
            ),
            pytest.param(
                'from app.core import events\n(e := events)\nx = e.event_bus\n',
                id='walrus-alias',
            ),
            pytest.param(
                'from app.core import events\n'
                'a = None\n'
                'def read():\n'
                '    a = b\n'
                '    return a.event_bus\n'
                'def bind():\n'
                '    global b\n'
                '    b = a\n'
                '    b = events\n'
                'bind()\n'
                'x = read()\n',
                id='cyclic-alias-chain',
            ),
            pytest.param(
                'import app.core.events\n'
                'def read():\n'
                '    a = b\n'
                '    return a.event_bus\n'
                'b = app.core.events\n'
                'x = read()\n',
                id='later-dotted-alias',
            ),
            pytest.param(
                'import app.core.events\n'
                'app = app.core\n'
                'app = app.events\n'
                'x = app.event_bus\n',
                id='self-rebinding-dotted-alias',
            ),
        ],
    )
    def test_both_gates_refuse_it(self, tmp_path: Path, source: str):
        module_dir = _module(tmp_path, source)
        assert any('event_bus' in v for v in _find_safety_violations(module_dir, []))
        assert any('event_bus' in e for e in validate_safety(module_dir, []))
