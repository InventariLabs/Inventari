"""The purpose-card gate holds the shape docs/purpose/README.md promises.

The README says a card has seven headings "and nothing else" and that every
module and every Core area has one. The gate used to check the seven headings
and the backend modules only, so a card with an extra section and a Core area
with no card both passed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_purpose_cards.py'

_CARD = '\n'.join(
    f'## {heading}\n\ntext\n'
    for heading in (
        'Job',
        'Whose job',
        'Inside the boundary',
        'Outside the boundary',
        'Own concepts / Borrowed',
        'Deliberately not done',
        'Switched off',
    )
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_purpose_cards', _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    """Ten backend modules, one Core area, and a card for each."""
    gate = _load()
    modules = tmp_path / 'backend' / 'app' / 'modules'
    for n in range(10):
        (modules / f'mod{n}').mkdir(parents=True)
        (modules / f'mod{n}' / 'manifest.json').write_text('{}')
    cards = tmp_path / 'docs' / 'purpose'
    cards.mkdir(parents=True)
    for n in range(10):
        (cards / f'mod{n}.md').write_text(_CARD)
    front = tmp_path / 'frontend' / 'src' / 'modules'
    for name in ('mod0', 'launcher', 'shared'):
        (front / name).mkdir(parents=True)
    (cards / 'core-launcher.md').write_text(_CARD)
    monkeypatch.setattr(gate, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(gate, 'BACKEND_DIR', tmp_path / 'backend')
    monkeypatch.setattr(gate, 'MODULES_DIR', modules)
    monkeypatch.setattr(gate, 'FRONTEND_MODULES_DIR', front)
    monkeypatch.setattr(gate, 'CARDS_DIR', cards)
    return gate, tmp_path


def test_a_complete_tree_passes(tree: tuple[ModuleType, Path]) -> None:
    gate, _ = tree
    assert gate.main() == 0


def test_a_card_with_an_extra_heading_fails(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    gate, root = tree
    card = root / 'docs' / 'purpose' / 'mod1.md'
    card.write_text(_CARD + '\n## Roadmap\n\nsoon\n')
    assert gate.main() == 1
    assert 'outside the shape: Roadmap' in capsys.readouterr().err


def test_a_core_area_without_a_card_fails(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    gate, root = tree
    (root / 'docs' / 'purpose' / 'core-launcher.md').unlink()
    assert gate.main() == 1
    assert 'core-launcher.md' in capsys.readouterr().err


def test_shared_components_need_no_card(tree: tuple[ModuleType, Path]) -> None:
    gate, _ = tree
    assert gate._core_areas() == ['launcher']


def test_a_card_for_something_that_is_gone_fails(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    gate, root = tree
    (root / 'docs' / 'purpose' / 'ghost.md').write_text(_CARD)
    assert gate.main() == 1
    assert 'ghost.md: no module or Core area' in capsys.readouterr().err
