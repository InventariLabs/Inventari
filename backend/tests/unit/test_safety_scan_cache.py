"""The AST safety scan is cached by content, and the cache cannot lie.

Discovery parses several hundred files in each of four workers on every
restart, and the verdict only changes when the files do. What matters is not
the speed-up but that a cached answer is never served for a state it was not
computed from — a stale "no violations" is a safety check that silently
stopped running.
"""

from pathlib import Path

import pytest

from app.core.module_safety_analysis import analyze_module_safety


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('INVENTARI_VALIDATION_CACHE_DIR', str(tmp_path / 'cache'))


def _module(tmp_path: Path, source: str, name: str = 'community_thing') -> Path:
    module_dir = tmp_path / name
    module_dir.mkdir(exist_ok=True)
    (module_dir / 'service.py').write_text(source, encoding='utf-8')
    return module_dir


def _keys(module_dir: Path, caps: list[str] | None = None) -> list[str]:
    return [f.subject for f in analyze_module_safety(module_dir, caps or [])]


class TestCacheCorrectness:
    def test_a_cached_run_matches_an_uncached_one(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'import subprocess\n')

        cached = analyze_module_safety(module_dir, [])
        fresh = analyze_module_safety(module_dir, [], use_cache=False)

        assert cached == fresh

    def test_the_second_call_does_not_reparse(self, tmp_path: Path, monkeypatch):
        module_dir = _module(tmp_path, 'import os\n')
        analyze_module_safety(module_dir, [])

        def _explode(*args, **kwargs):
            raise AssertionError('cache miss: the file was parsed again')

        monkeypatch.setattr('app.core.module_safety_analysis.ast.parse', _explode)

        assert analyze_module_safety(module_dir, [])


class TestInvalidation:
    def test_editing_a_file_invalidates(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'x = 1\n')
        assert _keys(module_dir) == []

        (module_dir / 'service.py').write_text('import subprocess\n', encoding='utf-8')

        assert 'subprocess' in _keys(module_dir)

    def test_adding_a_file_invalidates(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'x = 1\n')
        assert _keys(module_dir) == []

        (module_dir / 'extra.py').write_text('import socket\n', encoding='utf-8')

        assert 'socket' in _keys(module_dir)

    def test_removing_a_file_invalidates(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'import subprocess\n')
        (module_dir / 'extra.py').write_text('x = 1\n', encoding='utf-8')
        assert _keys(module_dir)

        (module_dir / 'service.py').unlink()

        assert _keys(module_dir) == []

    def test_declared_capabilities_are_part_of_the_key(self, tmp_path: Path):
        """The same bytes are a violation or not depending on the manifest."""
        module_dir = _module(tmp_path, 'import requests\n')

        without = analyze_module_safety(module_dir, [])
        with_cap = analyze_module_safety(module_dir, ['network'])

        assert without, 'undeclared network access must be reported'
        assert with_cap == [], 'declared capability must clear it'

    def test_identical_content_in_another_module_is_judged_separately(
        self, tmp_path: Path
    ):
        """CORE_EXEMPTIONS keys on module name, so the name must matter."""
        untrusted = _module(tmp_path, 'import subprocess\n', name='community_thing')
        exempt = _module(tmp_path, 'import subprocess\n', name='printing')

        assert _keys(untrusted), 'a community module may not use subprocess'
        assert _keys(exempt) == [], 'printing is exempted for subprocess'

    def test_the_checkout_own_printing_keeps_its_exemption(self):
        """The exemption on the real shipped module, not just on the name."""
        from pathlib import Path

        from app.core import module_safety_analysis

        own = (
            Path(module_safety_analysis.__file__).resolve().parent.parent
            / 'modules'
            / 'printing'
        )

        # The manifest's own capabilities, so the scan reads like discovery
        # runs it: what is left is the exemption question and nothing else.
        assert _keys(own, ['database', 'filesystem', 'process']) == [], (
            'the repo printing module may shell out'
        )


class TestResilience:
    def test_a_corrupt_cache_file_falls_back_to_scanning(self, tmp_path: Path):
        module_dir = _module(tmp_path, 'import subprocess\n')
        analyze_module_safety(module_dir, [])

        cache_dir = tmp_path / 'cache' / 'inventari-module-validation'
        for entry in cache_dir.iterdir():
            entry.write_text('{{{ not json', encoding='utf-8')

        assert 'subprocess' in _keys(module_dir), 'must rescan, not crash'

    def test_an_unwritable_cache_dir_does_not_break_the_scan(
        self, tmp_path: Path, monkeypatch
    ):
        """Caching is an optimisation; losing it must not lose the check."""
        monkeypatch.setenv('INVENTARI_VALIDATION_CACHE_DIR', '/proc/nonexistent')
        module_dir = _module(tmp_path, 'import subprocess\n')

        assert 'subprocess' in _keys(module_dir)
