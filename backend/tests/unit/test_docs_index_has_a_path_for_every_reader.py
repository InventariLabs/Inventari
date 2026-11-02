"""The docs index opens with four reader paths, and every guide has one.

``docs/README.md`` used to split its external guides into "External guides"
and "Technical reference", which put the user guide, the CLI, the demo, nine
module-author documents and the operator runbooks in one table — and the
operator documents were not in it at all: DEPLOYMENT.md and QUICK_DEPLOY.md
live at the repository root and the index never named them. The fix agreed in
the docs review is structural: reader paths (using, running, building on
Inventari, contributing to it), each external guide in exactly one of them, the operator documents reachable
with their update/backup/restore/troubleshooting sections linked by anchor, and
the technical reference (ERD, ADRs, subsystems, purpose cards) below as its own
section.

This test reads the index as a reader would: it splits the document at its
``##`` headings, looks at the links under each one, and holds the structure
above. The anchors are checked against the headings that actually exist in
DEPLOYMENT.md, because a link to ``#backups`` while the heading says
``## Database Backups`` is a link to nowhere that no path check sees.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_INDEX = _REPO_ROOT / 'docs' / 'README.md'

#: The reader paths, in the order the index opens with them.
_PATHS = (
    'Using the app',
    'Running and maintaining it',
    'Building on Inventari',
    'Contributing to Inventari',
)

#: Every external guide, and the one path it belongs to. The paths are
#: relative to docs/README.md, anchors included, exactly as linked.
_GUIDES = {
    'Using the app': (
        '../README.md#quick-start',
        'USER_GUIDE.md',
        'GALLERY.md',
        'FOCUS_MODE.md',
    ),
    'Running and maintaining it': (
        '../QUICK_DEPLOY.md',
        '../DEPLOYMENT.md',
        '../SECURITY.md',
        'SCALING.md',
        'SCALE_REPORT.md',
        'CLI.md',
        'DEMO.md',
        'OFF_DATABASE_SETUP.md',
        'GDPR_MANUAL_PROCEDURE.md',
    ),
    'Building on Inventari': (
        '../README.md#build-on-inventari',
        '../MODULE_QUICKSTART.md',
        '../examples/lot_certificates/README.md',
        '../MODULES_GUIDE.md',
        'FRONTEND_MODULE_GUIDE.md',
        'MODULE_ADVANCED_GUIDE.md',
        'MODULE_TESTING_GUIDE.md',
        'MODULE_CAPABILITIES.md',
        'MODULE_VERSIONING.md',
        'MODULE_NAMES.md',
        'subsystems/CONTRACTS_STABILITY.md',
        '../MODULE_LICENSING.md',
        'api/openapi.json',
        'api/ERRORS.md',
    ),
    'Contributing to Inventari': ('../CONTRIBUTING.md',),
}

#: The deployment sections the operator path links by anchor.
_DEPLOYMENT_ANCHORS = (
    'updating',
    'database-backups',
    'putting-a-backup-back',
    'rebuilding-on-a-new-server',
    'troubleshooting',
)

#: The technical reference keeps its own section, below the three paths.
_TECHNICAL_REFERENCE = (
    'ERD.md',
    'TECHNICAL_DECISIONS.md',
    'adr/',
    'subsystems/',
    'purpose/',
)

_LINK = re.compile(r'\[[^\]]+\]\(([^)]+)\)')
_HEADING = re.compile(r'^#{2,3} (.+)$', re.MULTILINE)


def _sections() -> dict[str, str]:
    chunks = re.split(r'^## ', _INDEX.read_text(encoding='utf-8'), flags=re.MULTILINE)[
        1:
    ]
    return {
        chunk.splitlines()[0].strip(): '\n'.join(chunk.splitlines()[1:])
        for chunk in chunks
    }


def _linked_targets(section: str) -> list[str]:
    return [
        target
        for target in _LINK.findall(section)
        if not target.startswith(('http://', 'https://', '#'))
    ]


def _guide_key(target: str) -> str:
    """What identifies a guide: its path, except for the README, whose
    sections are separate destinations (`#quick-start` belongs to using the
    app, `#build-on-inventari` to building on it)."""
    path = target.split('#', 1)[0]
    return target if path == '../README.md' else path


def _linked_paths(section: str) -> set[str]:
    return {_guide_key(target) for target in _linked_targets(section)}


def _slug(heading: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', heading.strip().lower())
    return re.sub(r'\s+', '-', slug)


class TestTheIndexOpensWithTheReaderPaths:
    def test_the_first_sections_are_the_paths(self) -> None:
        assert tuple(_sections())[: len(_PATHS)] == _PATHS

    @pytest.mark.parametrize('path', _PATHS)
    def test_each_path_is_a_reader(self, path: str) -> None:
        assert _sections()[path].strip(), f'{path} lists no document'


class TestEveryGuideSitsInExactlyOnePath:
    @pytest.mark.parametrize('path', _PATHS)
    def test_the_path_lists_exactly_its_guides(self, path: str) -> None:
        assert _linked_paths(_sections()[path]) == {
            _guide_key(g) for g in _GUIDES[path]
        }

    @pytest.mark.parametrize(
        'guide',
        [guide for guides in _GUIDES.values() for guide in guides],
    )
    def test_the_guide_is_in_exactly_one_path(self, guide: str) -> None:
        path = _guide_key(guide)
        owners = [p for p in _PATHS if path in _linked_paths(_sections()[p])]
        assert len(owners) == 1, f'{guide} is in {owners or "no"} path'


class TestTheOperatorDocumentsAreReachable:
    @pytest.mark.parametrize('document', ('../DEPLOYMENT.md', '../QUICK_DEPLOY.md'))
    def test_the_document_is_linked(self, document: str) -> None:
        assert document in _linked_paths(_sections()['Running and maintaining it'])

    @pytest.mark.parametrize('anchor', _DEPLOYMENT_ANCHORS)
    def test_the_deployment_anchor_names_a_real_heading(self, anchor: str) -> None:
        index = _INDEX.read_text(encoding='utf-8')
        deployment = (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')
        slugs = {_slug(heading) for heading in _HEADING.findall(deployment)}

        assert f'../DEPLOYMENT.md#{anchor}' in index
        assert anchor in slugs, f'DEPLOYMENT.md has no heading for #{anchor}'


class TestTheTechnicalReferenceStaysBelow:
    @pytest.mark.parametrize('entry', _TECHNICAL_REFERENCE)
    def test_the_entry_is_in_the_technical_reference(self, entry: str) -> None:
        sections = _sections()
        assert 'Technical reference' in sections
        assert entry in _linked_paths(sections['Technical reference'])
        first_reference = list(sections).index('Technical reference')
        assert first_reference == len(_PATHS), (
            'technical reference must follow the reader paths'
        )
