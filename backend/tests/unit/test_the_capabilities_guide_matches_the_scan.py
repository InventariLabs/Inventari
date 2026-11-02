"""The capabilities guide's lists are the scan's lists, and its manifests load.

``docs/MODULE_CAPABILITIES.md`` is where a module author learns what the
install-time scan refuses and what a manifest has to carry. Both had drifted
from the code: the forbidden calls left out ``import_module`` while the text
below them said dynamic import was free to use, and the manifest the guide
offered to copy lacked ``module_type``, a required field, so the schema
refused it. The tables here are read on every run and compared with
``app.core.module_safety``; every manifest a guide marks
``<!-- validated: manifest.json -->`` is loaded through the schema the
registry uses.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.core.module_manifest_schema import ManifestCapability, ModuleManifest
from app.core.module_safety import (
    CAPABILITY_MAP,
    FORBIDDEN_CALLS,
    FORBIDDEN_IMPORT_PREFIXES,
)

_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
_DOCS = _ROOT / 'docs'
_GUIDE = _DOCS / 'MODULE_CAPABILITIES.md'

#: A whole manifest a document hands the reader to copy.
_MARKED_MANIFEST = re.compile(
    r'<!-- validated: manifest\.json -->\s*```json\n([\s\S]*?)\n```'
)


def _section(heading: str) -> str:
    guide = _GUIDE.read_text(encoding='utf-8')
    start = guide.index(heading)
    end = guide.find('\n## ', start + len(heading))
    return guide[start : end if end != -1 else None]


def _first_column_spans(section: str) -> list[list[str]]:
    """The backticked names in the first cell of each table row."""
    rows = []
    for line in section.splitlines():
        if line.startswith('| `'):
            first_cell = line.split('|')[1]
            rows.append(re.findall(r'`([^`]+)`', first_cell))
    return rows


def test_the_forbidden_imports_table_is_the_scans_list() -> None:
    rows = _first_column_spans(
        _section(
            '## Forbidden Imports and Calls (always rejected, no capability override)'
        )
    )
    imports = {span for row in rows for span in row if not span.endswith('()')}
    assert imports == set(FORBIDDEN_IMPORT_PREFIXES)


def test_the_forbidden_calls_are_the_scans_calls() -> None:
    rows = _first_column_spans(
        _section(
            '## Forbidden Imports and Calls (always rejected, no capability override)'
        )
    )
    calls = {span[:-2] for row in rows for span in row if span.endswith('()')}
    assert calls == set(FORBIDDEN_CALLS)

    stated = re.search(r'`FORBIDDEN_CALLS = \{([^}]*)\}`', _section('## Validation'))
    assert stated, 'the Validation section no longer quotes FORBIDDEN_CALLS'
    assert set(re.findall(r"'([^']+)'", stated.group(1))) == set(FORBIDDEN_CALLS)


def test_each_capability_allows_what_the_scan_maps_to_it() -> None:
    """A name the forbidden list refuses first (``socket``, ``subprocess``)
    is never reached through a capability, so the table leaves it out; the
    builtin ``open`` is written as the call a reader types."""
    allowed: dict[str, set[str]] = {}
    for line in _section('## Available Capabilities').splitlines():
        if line.startswith('| `'):
            cells = line.split('|')
            capability = re.findall(r'`([^`]+)`', cells[1])[0]
            allowed[capability] = {
                span.removesuffix('()') for span in re.findall(r'`([^`]+)`', cells[2])
            }
    expected = {
        capability: {
            name.removeprefix('builtins.')
            for name in CAPABILITY_MAP[capability]
            if not name.startswith(FORBIDDEN_IMPORT_PREFIXES)
        }
        for capability in CAPABILITY_MAP
    }
    assert set(allowed) == {c.value for c in ManifestCapability} == set(CAPABILITY_MAP)
    assert allowed == expected


def _marked_manifests() -> list[tuple[str, str]]:
    found = []
    for document in sorted(_DOCS.glob('*.md')):
        for block in _MARKED_MANIFEST.findall(document.read_text(encoding='utf-8')):
            found.append((document.name, block))
    return found


def test_the_guides_mark_the_manifests_they_offer_to_copy() -> None:
    assert {name for name, _ in _marked_manifests()} >= {
        'MODULE_CAPABILITIES.md',
        'MODULE_VERSIONING.md',
    }


@pytest.mark.parametrize(
    ('document', 'block'),
    _marked_manifests(),
    ids=lambda value: value if value.endswith('.md') else '',
)
def test_a_manifest_a_guide_offers_to_copy_loads(document: str, block: str) -> None:
    ModuleManifest.model_validate(json.loads(block))
