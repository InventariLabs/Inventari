"""The README and the CHANGELOG name every document profile and its codes.

Both documents list the profiles that carry a country's paperwork vocabulary
("PL Magazyn", "UK Warehouse", ...) with the codes they put on receipts,
issues and moves. When "DE Lager" arrived, both lists went on describing four
profiles for a while, and a reader of the front door was told the product
speaks fewer paperwork languages than it does. The list a document gives is a
claim of completeness, so this test holds it against the profiles the code
ships: each profile that writes its own codes must be named, and the codes of
a receipt, an issue and a move must stand right beside the name.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.modules.warehouse.document_profile_service import PRESETS

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

# How far from a profile's name its codes may stand and still read as its own:
# the README writes them after the name, the CHANGELOG before it.
_BEFORE = 40
_AFTER = 80


def _own_codes() -> dict[str, tuple[str, ...]]:
    """Profile name -> the codes of a receipt, an issue and a move."""
    found: dict[str, tuple[str, ...]] = {}
    for name, preset in PRESETS.items():
        labels = preset.get('type_labels') or {}
        if all(labels.get(t) for t in ('IN', 'OUT', 'INT')):
            found[name] = tuple(labels[t] for t in ('IN', 'OUT', 'INT'))
    return found


def _problems(text: str) -> list[str]:
    problems = []
    for name, codes in _own_codes().items():
        at = text.find(name)
        if at < 0:
            problems.append(f'{name!r} is not named')
            continue
        before = text[max(0, at - _BEFORE) : at]
        after = text[at : at + len(name) + _AFTER]
        if not (all(c in before for c in codes) or all(c in after for c in codes)):
            problems.append(f'{name!r} is named without its codes {list(codes)}')
    return problems


def test_the_profiles_with_their_own_codes_are_the_ones_the_docs_expect() -> None:
    """A guard on the guard: if no profile carries codes, the checks below prove nothing."""
    assert {'PL Magazyn', 'UK Warehouse', 'DE Lager'} <= set(_own_codes())


@pytest.mark.parametrize('document', ['README.md', 'CHANGELOG.md'])
def test_a_document_names_every_profile_and_its_codes(document: str) -> None:
    path = _REPO_ROOT / document
    assert path.is_file(), f'{document} is not reachable from here'
    assert _problems(path.read_text(encoding='utf-8')) == []


def test_a_profile_missing_from_a_list_is_reported() -> None:
    text = '"PL Magazyn": PZ, WZ, MM. "UK Warehouse": GRN, DN, ST.'
    assert any('DE Lager' in p for p in _problems(text))
