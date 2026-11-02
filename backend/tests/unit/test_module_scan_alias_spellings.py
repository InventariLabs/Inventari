"""The safety scan follows a policed name through every way Python rebinds it."""

from pathlib import Path

import pytest

from app.cli.module_validator import validate_safety
from app.core.module_validator import _find_safety_violations

CALL_SPELLINGS = [
    pytest.param('im, x = import_module, 1\nim("os")\n', id='unpacking'),
    pytest.param('(im := import_module)("os")\n', id='direct-walrus-call'),
    pytest.param('im = import_module if x else len\nim("os")\n', id='ternary'),
    pytest.param('im = other or import_module\nim("os")\n', id='boolean-or'),
    pytest.param('def f(im=import_module):\n    im("os")\n', id='parameter-default'),
    pytest.param('def f(*, im=import_module):\n    im("os")\n', id='kwonly-default'),
    pytest.param('g = lambda im=import_module: im("os")\n', id='lambda-default'),
    pytest.param('for im in (import_module,):\n    im("os")\n', id='for-loop'),
    pytest.param('self.load = import_module\nself.load("os")\n', id='attribute-store'),
    pytest.param('fns = [import_module]\nfns[0]("os")\n', id='container-subscript'),
    pytest.param('list(map(import_module, ["os"]))\n', id='map-argument'),
    pytest.param('functools.partial(import_module, "os")()\n', id='partial'),
    pytest.param(
        'match import_module:\n    case im:\n        im("os")\n', id='match-capture'
    ),
    pytest.param('im, *x = import_module, 1\nim("os")\n', id='starred-unpacking'),
    pytest.param('*x, im = 1, import_module\nim("os")\n', id='starred-prefix'),
    pytest.param(
        'match import_module:\n    case 1 | im:\n        im("os")\n', id='match-or'
    ),
    pytest.param(
        'match [import_module]:\n    case [im]:\n        im("os")\n',
        id='match-sequence',
    ),
    pytest.param('d = {"i": import_module}\nd["i"]("os")\n', id='dict-container'),
    pytest.param(
        'class H:\n    fn: object = import_module\nH.fn("os")\n', id='class-annotated'
    ),
    pytest.param('open_it = open\nopen_it("f")\n', id='open-alias-stays-caught'),
    pytest.param(
        'im = getattr(importlib, "import_module")\nim("os")\n', id='getattr-result'
    ),
    pytest.param('fn = getattr(builtins, "open")\nfn("secret")\n', id='getattr-open'),
    pytest.param(
        'class H:\n    fn = import_module\nH.fn("os")\n', id='class-attribute-call'
    ),
    pytest.param(
        'class H:\n    fn = import_module\nx = H.fn\nx("os")\n',
        id='class-attribute-alias',
    ),
    pytest.param(
        'class H:\n    fn = import_module\ngetattr(H, "fn")("os")\n',
        id='class-getattr-call',
    ),
    pytest.param(
        'class H:\n    fn = import_module\nx = getattr(H, "fn")\nx("os")\n',
        id='class-getattr-alias',
    ),
    pytest.param(
        'g = getattr\nim = g(importlib, "import_module")\nim("os")\n',
        id='getattr-alias',
    ),
    pytest.param(
        'builtins.getattr(importlib, "import_module")("os")\n', id='getattr-qualified'
    ),
    pytest.param(
        'operator.attrgetter("import_module")(importlib)("os")\n', id='attrgetter'
    ),
    pytest.param(
        'ag = operator.attrgetter("import_module")\nag(importlib)("os")\n',
        id='attrgetter-bound',
    ),
    pytest.param('d = {"i": import_module}\nd.get("i")("os")\n', id='dict-get'),
    pytest.param('{}.get("i", import_module)("os")\n', id='dict-get-default'),
]

BUS_SPELLINGS = [
    pytest.param('e, f = events, None\nx = e.event_bus\n', id='unpacking'),
    pytest.param(
        'class H:\n    e: object = events\nx = H.e.event_bus\n', id='annotated'
    ),
    pytest.param('e = events or None\nx = e.event_bus\n', id='boolean'),
    pytest.param('e = events if c else None\nx = e.event_bus\n', id='ternary'),
    pytest.param('def f(e=events):\n    return e.event_bus\n', id='default'),
    pytest.param('f = lambda e=events: e.event_bus\n', id='lambda-default'),
    pytest.param('match events:\n    case e:\n        x = e.event_bus\n', id='match'),
    pytest.param('e = getattr(events, "event_bus")\n', id='getattr-leaf'),
    pytest.param('e = getattr(core, "events")\nx = e.event_bus\n', id='getattr-alias'),
    pytest.param(
        'x = getattr(getattr(core, "events"), "event_bus")\n', id='getattr-nested'
    ),
]

# No extra ``events`` import here: one would raise the depth ceiling and hide a miss.
# The binding line hands ``core.events`` over as a value and is refused on its own,
# so each case asserts the finding on the last line, where ``event_bus`` is read.
BARE_BUS_SPELLINGS = [
    pytest.param(
        'e = getattr(core, "events")\nx = getattr(e, "event_bus")\n',
        id='getattr-twice',
    ),
    pytest.param(
        'e, *f = core.events, None\nx = e.event_bus\n', id='starred-unpacking'
    ),
    pytest.param(
        'match core.events:\n    case 1 | e:\n        x = e.event_bus\n', id='match-or'
    ),
    pytest.param(
        'match [core.events]:\n    case [e]:\n        x = e.event_bus\n',
        id='match-sequence',
    ),
    pytest.param('self.e = core.events\nx = self.e.event_bus\n', id='attribute-store'),
    pytest.param('class H:\n    e = events\nx = H.e.event_bus\n', id='class-attribute'),
]

CLEAN = [
    pytest.param('im, x = len, 1\nim("os")\n', id='harmless-unpack'),
    pytest.param('def f(im=len):\n    im("os")\n', id='harmless-default'),
    pytest.param('list(map(len, ["os"]))\n', id='harmless-map'),
    pytest.param('d = {"i": len}\nd.get("i")("os")\n', id='harmless-dict-get'),
    pytest.param('g = getattr\ng(importlib, "reload")(x)\n', id='harmless-getattr'),
    pytest.param(
        'operator.attrgetter("reload")(importlib)(x)\n', id='harmless-attrgetter'
    ),
]


def _module(tmp_path: Path, source: str) -> Path:
    module_dir = tmp_path / 'community_thing'
    module_dir.mkdir()
    (module_dir / 'service.py').write_text(source)
    return module_dir


@pytest.mark.parametrize('body', CALL_SPELLINGS)
def test_a_policed_callable_is_caught_under_every_spelling(tmp_path: Path, body: str):
    source = 'from importlib import import_module\n' + body
    if 'open' in body:
        source = body
    module_dir = _module(tmp_path, source)

    assert _find_safety_violations(module_dir, [])
    assert len(validate_safety(module_dir, [])) == len(
        _find_safety_violations(module_dir, [])
    )


@pytest.mark.parametrize('body', BUS_SPELLINGS)
def test_the_event_bus_is_caught_under_every_spelling(tmp_path: Path, body: str):
    source = 'from app import core\nfrom app.core import events\n' + body
    module_dir = _module(tmp_path, source)

    assert _find_safety_violations(module_dir, [])
    assert len(validate_safety(module_dir, [])) == len(
        _find_safety_violations(module_dir, [])
    )


@pytest.mark.parametrize('body', BARE_BUS_SPELLINGS)
def test_the_event_bus_is_caught_without_a_second_import(tmp_path: Path, body: str):
    source = 'from app import core\n' + body
    if 'class' in body:
        source = 'from app.core import events\n' + body
    module_dir = _module(tmp_path, source)
    read_line = source.count('\n')

    findings = _find_safety_violations(module_dir, [])
    assert any(f'service.py:{read_line} ' in finding for finding in findings)
    assert len(validate_safety(module_dir, [])) == len(findings)


@pytest.mark.parametrize('body', CLEAN)
def test_a_harmless_callable_stays_allowed(tmp_path: Path, body: str):
    module_dir = _module(tmp_path, 'from importlib import import_module\n' + body)

    assert _find_safety_violations(module_dir, []) == []
