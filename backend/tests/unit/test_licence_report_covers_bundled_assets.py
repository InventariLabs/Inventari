"""The licence report must account for the static assets the frontend ships.

`THIRD_PARTY_LICENSES.md` is generated from the manifests plus hand-kept
sections, and nothing looked at `frontend/public`: the Fluent Emoji SVGs (MIT,
whose notice has to travel with the files) and the AI-provider brand marks
could ship with no entry at all. The coverage check lists the directory and
compares it against the report's assets table; the shipped report itself has
to carry the notice each kind of entry requires.
"""

import os
from pathlib import Path

import pytest

from scripts.check_licences_fresh import (
    _reported_asset_rows,
    asset_coverage_gaps,
    bundled_asset_directories,
)

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents above
#: this file, in the container the read-only mount docker-compose.yml names
#: with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_HEADER = """# Third-party licences

## Bundled frontend assets

| Package | Version | Licence | Note |
|---|---|---|---|
"""


def _write_report(tmp_path: Path, rows: str = '') -> Path:
    report = tmp_path / 'THIRD_PARTY_LICENSES.md'
    report.write_text(_HEADER + rows, encoding='utf-8')
    return report


class TestAssetCoverageGaps:
    def test_a_directory_with_no_row_is_named(self) -> None:
        missing, stale = asset_coverage_gaps({'emoji'}, {'emoji', 'logos'})

        assert missing == ['logos']
        assert stale == []

    def test_a_row_naming_no_directory_is_named(self) -> None:
        missing, stale = asset_coverage_gaps({'emoji', 'gone'}, {'emoji'})

        assert missing == []
        assert stale == ['gone']

    def test_full_coverage_has_nothing_to_say(self) -> None:
        assert asset_coverage_gaps(
            {'emoji', 'fonts', 'logos'}, {'fonts', 'logos', 'emoji'}
        ) == ([], [])


class TestTheAssetsTableIsRead:
    def test_rows_name_directories_under_frontend_public(self, tmp_path: Path) -> None:
        report = _write_report(
            tmp_path, '| `frontend/public/emoji` | bundled | MIT | Fluent Emoji |\n'
        )

        assert set(_reported_asset_rows(report)) == {'emoji'}

    def test_rows_of_other_sections_do_not_count(self, tmp_path: Path) -> None:
        report = tmp_path / 'THIRD_PARTY_LICENSES.md'
        report.write_text(
            '# Third-party licences\n\n## Backend runtime (1 packages)\n\n'
            '| Package | Version | Licence | Note |\n|---|---|---|---|\n'
            '| `fastapi` | 0.1.0 | MIT |  |\n',
            encoding='utf-8',
        )

        assert _reported_asset_rows(report) == {}

    def test_a_missing_section_is_no_coverage_not_a_crash(self, tmp_path: Path) -> None:
        report = tmp_path / 'THIRD_PARTY_LICENSES.md'
        report.write_text('# Third-party licences\n', encoding='utf-8')

        assert _reported_asset_rows(report) == {}


class TestTheDirectoryListing:
    def test_directories_count_and_files_do_not(self, tmp_path: Path) -> None:
        (tmp_path / 'emoji').mkdir()
        (tmp_path / 'logos').mkdir()
        (tmp_path / 'favicon.ico').write_bytes(b'x')

        assert bundled_asset_directories(tmp_path) == {'emoji', 'logos'}


class TestTheShippedReport:
    def test_every_asset_directory_is_covered(self) -> None:
        """The real files: no directory without a row, no row without a directory."""
        rows = _reported_asset_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')
        missing, stale = asset_coverage_gaps(
            set(rows), bundled_asset_directories(_REPO_ROOT / 'frontend' / 'public')
        )

        assert (missing, stale) == ([], [])

    def test_the_emoji_entry_carries_the_mit_notice_and_copyright(self) -> None:
        row = _reported_asset_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')['emoji']

        assert 'MIT' in row
        assert 'Copyright (c) Microsoft Corporation' in row
        assert 'frontend/public/emoji/LICENSE' in row

    def test_the_fonts_entry_carries_the_ofl_notice_and_copyright(self) -> None:
        row = _reported_asset_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')['fonts']

        assert 'OFL' in row
        assert 'Copyright 2020 The Plus Jakarta Sans Project Authors' in row
        assert 'frontend/public/fonts/OFL.txt' in row

    def test_the_logo_entry_says_trademarks_used_to_name_the_provider(self) -> None:
        row = _reported_asset_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')['logos']

        assert 'trademarks of their respective owners' in row
        assert 'used only to name the provider' in row
