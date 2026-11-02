"""The documents' forbidden-import list is the scan's list, not a memory of it.

A reader could not tell what would actually load. The guide listed
``app.schemas.*`` and ``app.services.*`` as forbidden — this repository's
linting rule for its own modules, not the install-time scan's — and in the
same document told a community author to inherit ``app.database.Base``, which
the scan refuses outright. The block below is read out of ``MODULES_GUIDE.md``
on every run and compared with ``FORBIDDEN_IMPORT_PREFIXES`` itself, so the
guide can neither forget an entry nor invent one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.core.module_safety import FORBIDDEN_IMPORT_PREFIXES, MODULE_IMPORT_SURFACE
from app.core.module_safety_analysis import on_module_import_surface

BLOCK_START = '<!-- module-safety-forbidden-imports:start -->'
BLOCK_END = '<!-- module-safety-forbidden-imports:end -->'

SURFACE_START = '<!-- module-import-surface:start -->'
SURFACE_END = '<!-- module-import-surface:end -->'

#: The one sentence a community author must never read again: the core's Base
#: lives in ``app.database``, and the scan refuses that import at load.
THE_SENTENCE_THAT_WAS_WRONG = 'app.database.Base'


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))


def _guide() -> str:
    return (_repo_root() / 'MODULES_GUIDE.md').read_text(encoding='utf-8')


def _quickstart() -> str:
    return (_repo_root() / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')


@pytest.mark.unit
def test_the_guides_forbidden_imports_are_the_ones_the_scan_refuses() -> None:
    guide = _guide()
    match = re.search(
        re.escape(BLOCK_START) + r'(.*?)' + re.escape(BLOCK_END), guide, re.DOTALL
    )
    assert match, f'MODULES_GUIDE.md carries no {BLOCK_START} block'

    listed = set(re.findall(r'^- `([^`]+)`$', match.group(1), re.MULTILINE))

    assert listed == set(FORBIDDEN_IMPORT_PREFIXES)
    assert listed, 'the block lists nothing — a reader learns nothing from it'


@pytest.mark.unit
def test_the_guide_no_longer_sends_a_community_model_to_the_core_base() -> None:
    guide = _guide()

    assert THE_SENTENCE_THAT_WAS_WRONG not in guide
    assert 'app.core.contracts import ModuleModelBase' in guide


@pytest.mark.unit
def test_the_guides_declared_surface_is_the_scans() -> None:
    """A guide that lists a path the scan refuses, or forgets one, misleads."""
    guide = _guide()
    match = re.search(
        re.escape(SURFACE_START) + r'(.*?)' + re.escape(SURFACE_END),
        guide,
        re.DOTALL,
    )
    assert match, f'MODULES_GUIDE.md carries no {SURFACE_START} block'

    listed = set(re.findall(r'^- `([^`]+)`$', match.group(1), re.MULTILINE))

    assert listed == set(MODULE_IMPORT_SURFACE)
    assert listed, 'the block lists nothing — a reader learns nothing from it'


@pytest.mark.unit
def test_the_guides_import_examples_stay_on_the_surface() -> None:
    """Every `from app.…` example is one a community module may actually write.

    The blocks above are the promise; the code in the middle of the document is
    what an author copies. A sample importing ``app.core.deps`` reads as
    sanctioned and is refused at install.
    """
    for text in (_guide(), _quickstart()):
        reached = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('import app.'):
                reached.append(stripped[len('import ') :].split()[0].rstrip(','))
            elif stripped.startswith('from app.'):
                reached.append(stripped[len('from ') :].split()[0])
        assert reached, 'the guides show no import — this test would prove nothing'
        assert [
            name for name in reached if not on_module_import_surface(name, 'my_module')
        ] == []


@pytest.mark.unit
def test_the_guide_names_the_warehouse_as_the_largest_example_and_says_what_it_still_reaches() -> (
    None
):
    """The warehouse is the largest module, not a pure example of the public
    surface: the baseline freezes what it still imports directly, and a module
    copied from it is refused at install. The guide says so, and sends an
    author who wants code to copy to the example that uses only the SDK."""
    guide = _guide()

    assert 'The largest example is `app/modules/warehouse`' in guide
    assert 'module_import_surface_baseline.txt' in guide
    assert 'examples/lot_certificates' in guide
    assert 'Nothing under `app.models`' not in guide


@pytest.mark.unit
def test_the_quickstart_names_the_same_model_base() -> None:
    assert 'ModuleModelBase' in _quickstart()
    assert THE_SENTENCE_THAT_WAS_WRONG not in _quickstart()
