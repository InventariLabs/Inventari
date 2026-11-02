"""The licence report's hand-kept image sections must follow the stack.

`THIRD_PARTY_LICENSES.md` is generated, but its container-image and
system-layer sections are written by hand in `app/cli/_deps_licenses_report.py`
and nothing compared them to what the stack pulls: a bump of three images in
the compose files updated the report and left the generator behind, so the next
regeneration would have quietly written the old versions back. The checker now
reads the compose files and the Dockerfiles; these tests pin what it reads and
that the shipped report, and the generator that writes it, agree with them.
"""

import os
from pathlib import Path

import pytest

from app.cli._deps_licenses_report import IMAGE_COMPONENTS, SYSTEM_COMPONENTS
from scripts.check_licences_fresh import (
    compose_images,
    image_coverage_gaps,
    reported_images,
    system_packages_gone,
)

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents above
#: this file, in the container the read-only mount docker-compose.yml names
#: with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_TABLE_HEAD = '| Package | Version | Licence | Note |\n|---|---|---|---|\n'


def _report(tmp_path: Path, images: str = '', system: str = '') -> Path:
    report = tmp_path / 'THIRD_PARTY_LICENSES.md'
    report.write_text(
        '# Third-party licences\n\n'
        '## Backend and backup images — system layer\n\n'
        + _TABLE_HEAD
        + system
        + '\n## Container images\n\n'
        + _TABLE_HEAD
        + images
        + '\n## Bundled frontend assets\n',
        encoding='utf-8',
    )
    return report


class TestReportedImages:
    def test_a_row_with_the_tag_in_its_name_is_that_reference(self, tmp_path):
        report = _report(
            tmp_path, '| `valkey/valkey:9.1.2-alpine` | 9.1.2 | BSD |  |\n'
        )

        assert reported_images(report) == {'valkey/valkey:9.1.2-alpine'}

    def test_a_row_whose_tag_is_the_version_column_is_rebuilt(self, tmp_path):
        report = _report(tmp_path, '| `rclone/rclone` | 1.75.1 | MIT |  |\n')

        assert reported_images(report) == {'rclone/rclone:1.75.1'}

    def test_rows_of_other_sections_are_not_images(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')

        assert reported_images(report) == set()


class TestComposeImages:
    def test_literal_references_are_collected_from_every_compose_file(self, tmp_path):
        (tmp_path / 'docker-compose.yml').write_text(
            'services:\n  db:\n    image: postgres:17-alpine\n', encoding='utf-8'
        )
        (tmp_path / 'docker-compose.prod.yml').write_text(
            "services:\n  cache:\n    image: 'valkey/valkey:9.1.2-alpine'  # pinned\n",
            encoding='utf-8',
        )

        assert compose_images(tmp_path) == {
            'postgres:17-alpine',
            'valkey/valkey:9.1.2-alpine',
        }

    def test_a_reference_built_from_a_variable_names_nothing_to_quote(self, tmp_path):
        (tmp_path / 'docker-compose.yml').write_text(
            'services:\n  app:\n    image: ${REGISTRY}/app:${TAG}\n', encoding='utf-8'
        )

        assert compose_images(tmp_path) == set()

    def test_a_service_that_is_built_pulls_no_image(self, tmp_path):
        (tmp_path / 'docker-compose.yml').write_text(
            'services:\n  backend:\n    build:\n      context: ./backend\n',
            encoding='utf-8',
        )

        assert compose_images(tmp_path) == set()


class TestImageCoverageGaps:
    def test_a_bumped_image_is_missing_at_the_new_tag_and_stale_at_the_old(self):
        unlisted, stale = image_coverage_gaps(
            {'valkey/valkey:9.1.1-alpine'}, {'valkey/valkey:9.1.2-alpine'}
        )

        assert unlisted == ['valkey/valkey:9.1.2-alpine']
        assert stale == ['valkey/valkey:9.1.1-alpine']

    def test_matching_sets_have_nothing_to_say(self):
        assert image_coverage_gaps({'caddy:2-alpine'}, {'caddy:2-alpine'}) == (
            [],
            [],
        )


class TestSystemPackagesGone:
    def _root(self, tmp_path: Path, dockerfile: str) -> Path:
        (tmp_path / 'docker').mkdir()
        (tmp_path / 'docker' / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
        return tmp_path

    def test_a_package_a_dockerfile_still_names_stands(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN apk add --no-cache age postgresql-client\n')

        assert system_packages_gone(report, root) == []

    def test_a_row_for_a_removed_package_is_named(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN apk add --no-cache postgresql-client\n')

        assert system_packages_gone(report, root) == ['age']

    def test_a_comment_that_names_a_removed_package_does_not_keep_its_row(
        self, tmp_path
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path,
            '# age used to be installed\nRUN apk add --no-cache postgresql-client\n',
        )

        assert system_packages_gone(report, root) == ['age']

    def test_a_shell_comment_after_an_install_does_not_keep_its_row(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path, 'RUN apk add postgresql-client # age used to be installed\n'
        )

        assert system_packages_gone(report, root) == ['age']

    @pytest.mark.parametrize(
        'line',
        [
            'RUN apk add postgresql-client;# age used to be installed\n',
            'RUN apk add postgresql-client&&# age used to be installed\n',
            'RUN apk add postgresql-client||# age used to be installed\n',
            'RUN (apk add postgresql-client)# age used to be installed\n',
        ],
        ids=['semicolon', 'and', 'or', 'subshell'],
    )
    def test_a_comment_straight_after_an_operator_does_not_keep_its_row(
        self, tmp_path, line
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, line)

        assert system_packages_gone(report, root) == ['age']

    def test_a_word_around_an_operator_keeps_its_text(self, tmp_path):
        """A command right after an operator is run, not read as a comment."""
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN apk add postgresql-client;apk add age\n')

        assert system_packages_gone(report, root) == []

    @pytest.mark.parametrize(
        'line',
        [
            'RUN curl -fsSL https://example.org/dl#age -o /tmp/x\n',
            'RUN echo "installing # age" && true\n',
            "RUN echo 'installing # age' && true\n",
        ],
        ids=['url-fragment', 'double-quoted', 'single-quoted'],
    )
    def test_a_hash_that_does_not_start_a_comment_keeps_the_text(self, tmp_path, line):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, line)

        assert system_packages_gone(report, root) == []

    def test_an_escaped_quote_does_not_end_the_quoted_text(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN echo "a \\" # marker" && apk add age\n')

        assert system_packages_gone(report, root) == []

    def test_an_escaped_space_does_not_start_a_comment(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN echo a\\ # marker && apk add age\n')

        assert system_packages_gone(report, root) == []

    def test_a_comment_after_an_escaped_quote_is_still_a_comment(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN echo "a \\" b" # age used to be installed\n')

        assert system_packages_gone(report, root) == ['age']

    def test_a_quote_continued_onto_the_next_line_is_still_open(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN echo "a \\\n b # marker" && apk add age\n')

        assert system_packages_gone(report, root) == []

    @pytest.mark.parametrize(
        'dockerfile',
        [
            'RUN <<EOF\necho "a\n b # marker" && apk add age\nEOF\n',
            'RUN echo "a \\\n\n b # marker" && apk add age\n',
            'RUN <<EOF\necho "a\n# b"\necho "c # marker" && apk add age\nEOF\n',
            'RUN <<EOF\necho "a\n# b" && apk add age\nEOF\n',
        ],
        ids=[
            'heredoc',
            'empty-continuation-line',
            'hash-line-in-heredoc',
            'install-after-hash-line-in-heredoc',
        ],
    )
    def test_a_quote_open_across_physical_lines_keeps_the_install(
        self, tmp_path, dockerfile
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, dockerfile)

        assert system_packages_gone(report, root) == []

    def test_an_indented_comment_line_inside_a_continuation_keeps_the_install(
        self, tmp_path
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path, 'RUN echo ok \\\n    # ignored \\\n    && apk add age\n'
        )

        assert system_packages_gone(report, root) == []

    def test_a_quote_in_a_comment_line_does_not_open_a_quoted_argument(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path,
            'RUN echo "a \\\n    # ignored " \\\n    b # marker" && apk add age\n',
        )

        assert system_packages_gone(report, root) == []

    def test_a_shell_comment_runs_on_through_a_continued_line(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path, 'RUN apk add postgresql-client # used to be \\\n  age\n'
        )

        assert system_packages_gone(report, root) == ['age']

    def test_a_comment_line_inside_a_continued_instruction_is_dropped(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path,
            'RUN apk add \\\n# age used to be installed\n    postgresql-client\n',
        )

        assert system_packages_gone(report, root) == ['age']

    def test_a_shell_comment_line_in_a_heredoc_does_not_keep_its_row(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path, 'RUN <<EOF\napk add postgresql-client\n# age\nEOF\n'
        )

        assert system_packages_gone(report, root) == ['age']

    def test_a_comment_holding_a_quote_keeps_its_instruction_whole(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'RUN echo "$(echo " #")" && apk add age\n')

        assert system_packages_gone(report, root) == []

    @pytest.mark.parametrize(
        'line',
        [
            "RUN apk add postgresql-client # age isn't installed\n",
            'RUN apk add postgresql-client # "age" is not installed\n',
            'RUN echo "it\'s" && apk add postgresql-client # age (gone) & "dropped"\n',
        ],
        ids=['apostrophe', 'double-quotes', 'after-a-quoted-argument'],
    )
    def test_a_comment_holding_quotes_after_plain_shell_does_not_keep_its_row(
        self, tmp_path, line
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, line)

        assert system_packages_gone(report, root) == ['age']

    @pytest.mark.parametrize(
        'dockerfile',
        [
            'RUN echo ${UNSET:- # marker} && apk add age\n',
            'RUN echo `echo # marker` && apk add age\n',
            "RUN echo $'it\\'s # marker' && apk add age\n",
            'RUN echo "$(echo "it\'s" # marker)" && apk add age\n',
            'RUN <<EOF\nxargs apk add <<X\n # marker age\nX\nEOF\n',
            'COPY <<EOF /etc/packages\n # marker age\nEOF\n',
        ],
        ids=[
            'parameter-expansion',
            'command-substitution',
            'ansi-c-quoting',
            'quote-inside-command-substitution',
            'shell-heredoc',
            'not-a-run',
        ],
    )
    def test_a_hash_in_text_this_reader_does_not_follow_keeps_the_install(
        self, tmp_path, dockerfile
    ):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, dockerfile)

        assert system_packages_gone(report, root) == []

    def test_the_escape_directive_names_the_continuation_character(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(
            tmp_path,
            '# escape=`\nRUN apk add postgresql-client # used to be `\n  age\n',
        )

        assert system_packages_gone(report, root) == ['age']

    def test_a_word_that_merely_contains_the_name_does_not_count(self, tmp_path):
        report = _report(tmp_path, system='| `age` | distro | BSD-3-Clause |  |\n')
        root = self._root(tmp_path, 'FROM python:3.14-slim AS image\nRUN usage\n')

        assert system_packages_gone(report, root) == ['age']

    def test_one_surviving_package_keeps_a_multi_package_row(self, tmp_path):
        report = _report(
            tmp_path, system='| `libpango / libcairo` | distro | LGPL-2.1 |  |\n'
        )
        root = self._root(tmp_path, 'RUN apt-get install -y libpango-1.0-0\n')

        assert system_packages_gone(report, root) == []


class TestTheShippedStack:
    def test_the_report_names_every_image_the_compose_files_pull(self):
        unlisted, stale = image_coverage_gaps(
            reported_images(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md'),
            compose_images(_REPO_ROOT),
        )

        assert unlisted == [], unlisted
        assert stale == [], stale

    def test_the_generator_would_write_the_same_images(self):
        """The hand-kept table lives in the generator; a regeneration reads it."""
        written = {
            d.name if ':' in d.name else f'{d.name}:{d.version}'
            for d in IMAGE_COMPONENTS
        }

        unlisted, stale = image_coverage_gaps(written, compose_images(_REPO_ROOT))

        assert unlisted == [], unlisted
        assert stale == [], stale

    def test_the_system_layer_rows_are_still_installed_somewhere(self):
        gone = system_packages_gone(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md', _REPO_ROOT)

        assert gone == [], gone

    def test_the_generator_and_the_report_describe_the_same_system_layer(self):
        report = _REPO_ROOT / 'THIRD_PARTY_LICENSES.md'
        text = report.read_text(encoding='utf-8')

        for component in SYSTEM_COMPONENTS:
            assert f'`{component.name}`' in text
