"""CI drift detection: file paths referenced in public docs must exist.

The rules live in ``backend/scripts/check_docs_paths.py`` — one implementation,
three readers: this test, ``make lint`` on the host, and ``pytest`` inside the
backend container.

WHY IT NO LONGER SKIPS. It used to skip whenever the docs directory was not
mounted, and it was not mounted in the containers everybody works in, so the
suite reported green by skipping while the check itself was red on ``dev``:
five broken references nobody could see, because the only place the colour
showed was a CI run, and CI ran on ``main`` alone. ``docker-compose.yml`` now
mounts the documents into the backend container, so this test measures them
there; and a document it cannot see is now a failure rather than a skip, so a
partial mount can never turn into a green run that measured a smaller input
than it claims.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CHECKER = Path(__file__).resolve().parents[2] / 'scripts' / 'check_docs_paths.py'


def _load_checker():
    spec = importlib.util.spec_from_file_location('check_docs_paths', _CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
class TestDocsPathsDrift:
    """Backticked file paths in public docs must resolve in the tree."""

    def test_referenced_paths_exist(self) -> None:
        checker = _load_checker()
        missing = checker.missing_required()
        assert not missing, (
            'public docs are not reachable from here, so this check would scan '
            'a smaller input than it claims: '
            + ', '.join(missing)
            + '. Run on the host, or point INVENTARI_REPO_ROOT at the checkout '
            '— docker-compose.yml mounts it and sets that variable for the '
            'backend service.'
        )

        broken = checker.find_broken(checker.iter_public_docs())
        assert not broken, (
            'Public docs reference paths that do not exist:\n  '
            + '\n  '.join(broken)
            + '\n'
            + checker.FIX_HINT
        )


def _tree(tmp_path: Path) -> Path:
    """A repository with one real file and Markdown documents in places no list named."""
    (tmp_path / 'backend' / 'app').mkdir(parents=True)
    (tmp_path / 'backend' / 'app' / 'real.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'backend' / 'tests').mkdir()
    (tmp_path / 'backend' / 'tests' / 'README.md').write_text(
        'See `backend/app/real.py`.\n', encoding='utf-8'
    )
    (tmp_path / 'DEPLOYMENT.md').write_text('See `backend/app/real.py`.\n')
    (tmp_path / 'node_modules' / 'pkg').mkdir(parents=True)
    (tmp_path / 'node_modules' / 'pkg' / 'README.md').write_text(
        'See `backend/app/ghost.py`.\n', encoding='utf-8'
    )
    (tmp_path / 'docs' / 'plans').mkdir(parents=True)
    (tmp_path / 'docs' / 'plans' / 'private.md').write_text(
        'See `backend/app/ghost.py`.\n', encoding='utf-8'
    )
    return tmp_path


@pytest.mark.integration
class TestEveryMarkdownDocumentIsRead:
    """The gate reads the documents the repository has, not a list somebody keeps."""

    def test_a_bad_path_in_a_document_no_list_names_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker = _load_checker()
        root = _tree(tmp_path)
        monkeypatch.setattr(checker, '_ROOT', root)
        assert checker.find_broken(checker.iter_public_docs()) == []

        (root / 'backend' / 'tests' / 'README.md').write_text(
            'See `backend/tests/integration/nonexistent_probe.py`.\n', encoding='utf-8'
        )
        broken = checker.find_broken(checker.iter_public_docs())
        assert broken == [
            'backend/tests/README.md:1: `backend/tests/integration/nonexistent_probe.py`'
        ]

        (root / 'backend' / 'tests' / 'README.md').write_text('fine\n')
        (root / 'DEPLOYMENT.md').write_text('See `backend/app/ghost.py`.\n')
        assert [
            b.split(':')[0] for b in checker.find_broken(checker.iter_public_docs())
        ] == ['DEPLOYMENT.md']

    def test_dependencies_and_private_docs_are_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker = _load_checker()
        root = _tree(tmp_path)
        monkeypatch.setattr(checker, '_ROOT', root)
        read = {p.relative_to(root).as_posix() for p in checker._walked_markdown()}
        assert read == {'DEPLOYMENT.md', 'backend/tests/README.md'}

    def test_the_tracked_files_are_the_public_set_when_git_lists_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker = _load_checker()
        root = _tree(tmp_path)
        listing = b'DEPLOYMENT.md\0backend/tests/README.md\0'
        monkeypatch.setattr(checker, '_ROOT', root)
        monkeypatch.setattr(
            checker.subprocess,
            'run',
            lambda *a, **k: checker.subprocess.CompletedProcess(a, 0, listing, b''),
        )
        assert [p.relative_to(root).as_posix() for p in checker.iter_public_docs()] == [
            'DEPLOYMENT.md',
            'backend/tests/README.md',
        ]

    def test_the_documents_a_named_list_once_left_out_are_read_here(self) -> None:
        checker = _load_checker()
        read = {
            p.relative_to(checker._ROOT).as_posix() for p in checker.iter_public_docs()
        }
        assert {
            'backend/tests/README.md',
            'DEPLOYMENT.md',
            'MODULE_LICENSING.md',
        } <= read

    def test_directories_an_install_creates_are_not_required_in_the_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The licence report tells the reader to install both dependency trees first.

        CI's backend job never installs the frontend's, so a gate that demanded
        `frontend/node_modules` was red there and green on every laptop. The
        same holds for the build output `frontend/dist/`."""
        checker = _load_checker()
        root = _tree(tmp_path)
        monkeypatch.setattr(checker, '_ROOT', root)
        (root / 'DEPLOYMENT.md').write_text(
            'Install `backend/.venv` and `frontend/node_modules` first.\n'
            'Without /app the backend writes to `backend/uploads`.\n'
            'The phone budget needs a built `frontend/dist/`.\n'
        )
        assert checker.find_broken(checker.iter_public_docs()) == []

    def test_a_near_name_of_an_install_directory_is_still_a_dead_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the two documented directories are exempt, not whatever resembles them."""
        checker = _load_checker()
        root = _tree(tmp_path)
        monkeypatch.setattr(checker, '_ROOT', root)
        (root / 'DEPLOYMENT.md').write_text(
            'See `backend/.venv2`, `frontend/node_modules_old` and `backend/app/gone.py`.\n'
        )
        broken = checker.find_broken(checker.iter_public_docs())
        assert sorted(b.split(': ', 1)[1] for b in broken) == [
            '`backend/.venv2`',
            '`backend/app/gone.py`',
            '`frontend/node_modules_old`',
        ]


@pytest.mark.integration
class TestLineNumberReferences:
    """A `file:123` pointer outside the ADRs is refused: it rots with the next edit."""

    def test_a_line_number_pointer_is_reported_outside_adrs(
        self, tmp_path: Path
    ) -> None:
        checker = _load_checker()
        (tmp_path / 'docs' / 'adr').mkdir(parents=True)
        (tmp_path / 'backend').mkdir()
        (tmp_path / 'backend' / 'x.py').write_text('x = 1\n')
        body = 'See `backend/x.py:1` and `backend/x.py`.\n'
        guide = tmp_path / 'docs' / 'GUIDE.md'
        adr = tmp_path / 'docs' / 'adr' / 'ADR-001.md'
        guide.write_text(body)
        adr.write_text(body)
        checker._ROOT = tmp_path

        found = checker.find_broken([guide, adr])

        assert len(found) == 1
        assert found[0].startswith('docs/GUIDE.md:1:')
        assert 'backend/x.py:1' in found[0]
