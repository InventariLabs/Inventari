"""A module name is not its first letters.

The capability scan matched imports by prefix, so ``opening_stock_service``
read as ``open`` (filesystem) and ``system_health`` as ``sys`` (process),
and a module that never touched either was refused at load. The boundary
between "this module" and "a module inside it" is the dot.
"""

from pathlib import Path

import pytest

from app.core.module_safety_analysis import analyze_module_safety


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('INVENTARI_VALIDATION_CACHE_DIR', str(tmp_path / 'cache'))


def _module(tmp_path: Path, source: str) -> Path:
    module_dir = tmp_path / 'community_thing'
    module_dir.mkdir(exist_ok=True)
    (module_dir / 'router.py').write_text(source, encoding='utf-8')
    (module_dir / 'opening_stock_service.py').write_text('X = 1\n', encoding='utf-8')
    return module_dir


def _kinds(module_dir: Path) -> list[tuple[str, str]]:
    return [(f.kind, f.subject) for f in analyze_module_safety(module_dir, [])]


@pytest.mark.unit
class TestAModuleNameIsNotItsFirstLetters:
    def test_a_sibling_starting_with_open_is_not_the_filesystem(self, tmp_path):
        module_dir = _module(
            tmp_path,
            'from .opening_stock_service import X\nimport system_health\n',
        )
        assert _kinds(module_dir) == []

    def test_the_real_thing_is_still_caught(self, tmp_path):
        module_dir = _module(tmp_path, 'import os.path\nimport sys\n')
        subjects = {subject for _, subject in _kinds(module_dir)}
        assert {'os.path', 'sys'} <= subjects
