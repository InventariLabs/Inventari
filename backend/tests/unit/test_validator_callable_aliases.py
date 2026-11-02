"""A forbidden callable stays forbidden under any local name.

The call matcher compared the spelling at the call site, so
``from importlib import import_module as im; im(...)`` read as a call to
``im`` and passed. Both gates share one scanner and are checked here.
"""

from pathlib import Path

import pytest

from app.cli.module_validator import validate_safety
from app.core.module_validator import _find_safety_violations


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # A verdict served from the shared cache would skip the scan under test.
    monkeypatch.setenv('INVENTARI_VALIDATION_CACHE_DIR', str(tmp_path / 'cache'))


def _module(tmp_path: Path, source: str) -> Path:
    module_dir = tmp_path / 'community_thing'
    module_dir.mkdir()
    (module_dir / 'service.py').write_text(source)
    return module_dir


FORBIDDEN_SOURCES = [
    "from importlib import import_module as im\nim('app.core.events')\n",
    "from builtins import __import__ as imp\nimp('app.core.events')\n",
    "import importlib\nim = importlib.import_module\nim('x')\n",
    "import importlib\nim: object = importlib.import_module\nim('x')\n",
    # One name bound to two policed callables: a single-valued map flipped
    # between them on every pass and the scan never ended.
    "import importlib\nfn = open\nfn = importlib.import_module\nfn('x')\n",
    "import importlib\nrun = importlib.import_module\nrun = eval\nrun('x')\n",
    "import importlib\n(im := importlib.import_module)\nim('x')\n",
    "from importlib import import_module\nfirst = import_module\nsecond = first\nsecond('x')\n",
]

BENIGN_SOURCES = [
    "from json import loads as im\nim('1')\n",
    'def a(p):\n    fn = p.open\n    return fn\n\ndef b():\n    fn = len\n    return fn\n',
    "def im(x):\n    return x\nim('app.core.events')\n",
    'from importlib import import_module as im\nvalue = im\n',
]


@pytest.mark.parametrize('source', FORBIDDEN_SOURCES)
def test_registry_gate_catches_aliased_forbidden_call(tmp_path: Path, source: str):
    violations = _find_safety_violations(_module(tmp_path, source), [])

    assert any('forbidden' in v.lower() for v in violations), violations


@pytest.mark.parametrize('source', FORBIDDEN_SOURCES)
def test_cli_gate_catches_aliased_forbidden_call(tmp_path: Path, source: str):
    assert validate_safety(_module(tmp_path, source), []), source


@pytest.mark.parametrize('source', BENIGN_SOURCES)
def test_renamed_benign_calls_pass(tmp_path: Path, source: str):
    module_dir = _module(tmp_path, source)

    assert _find_safety_violations(module_dir, []) == []
    assert validate_safety(module_dir, []) == []
