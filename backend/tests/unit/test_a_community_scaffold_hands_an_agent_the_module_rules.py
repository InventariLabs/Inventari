"""`module new-community` writes the rules an AI coding agent needs into the package.

A package lives in its own repository (Path B of MODULE_QUICKSTART.md), so an
agent started inside it never sees the repository's AGENTS.md files. The
scaffold carries the few rules an agent breaks first, and the quickstart names
the same commands the generated file does — a command the file names that the
document does not, or that does not run in a fresh package, sends the agent
down a path nobody checked.
"""

import os
import re
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli._module_scaffold import scaffold_community_module
from manage import app

MODULE = 'warranty_tracker'


@pytest.fixture
def package(tmp_path):
    scaffold_community_module(MODULE, output_dir=str(tmp_path / 'workspace'))
    return tmp_path / 'workspace' / MODULE


def _quickstart() -> str:
    root = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    return (root / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')


def _commands(markdown: str) -> list[str]:
    blocks = re.findall(r'```bash\n(.*?)\n```', markdown, re.DOTALL)
    return [' '.join(block.replace('\\\n', ' ').split()) for block in blocks]


@pytest.mark.unit
class TestTheScaffoldWritesInstructionsForAnAgent:
    def test_agents_md_states_the_rules_an_agent_breaks_first(self, package):
        text = (package / 'AGENTS.md').read_text(encoding='utf-8')

        for rule in (
            'app.core.module_sdk',
            'app.core.contracts',
            'app.core.public_api',
            'app.models',
            'en, pl, de, fr, es',
            'ModuleModelBase',
            'backend/migrations',
            'purpose card',
            'module validate',
        ):
            assert rule in text, f'the generated AGENTS.md no longer says {rule!r}'

    def test_agents_md_links_the_full_docs_at_the_platforms_version(self, package):
        from app.core.version import get_platform_version

        text = (package / 'AGENTS.md').read_text(encoding='utf-8')

        assert f'/blob/v{get_platform_version()}/MODULES_GUIDE.md' in text
        assert f'/blob/v{get_platform_version()}/backend/AGENTS.md' in text

    def test_agents_md_says_how_the_frontend_specs_run_and_what_the_staging_may_touch(
        self, package
    ):
        text = (package / 'AGENTS.md').read_text(encoding='utf-8')

        for sentence in (
            '`frontend/tests/`',
            'npx vitest run --experimental.fsModuleCache=false',
            'stops the backend',
            'does not break',
        ):
            assert sentence in text, (
                f'the generated AGENTS.md no longer says {sentence!r}'
            )

    def test_agents_md_names_the_components_the_sdk_does_not_export(self, package):
        text = (package / 'AGENTS.md').read_text(encoding='utf-8')

        for component in ('`Sheet`', '`ListControlBar`', '`DateInput`'):
            assert component in text, (
                f'the generated AGENTS.md does not warn that {component} is not in '
                f'@/module-sdk'
            )

    def test_agents_md_says_what_the_first_version_is(self, package):
        text = (package / 'AGENTS.md').read_text(encoding='utf-8')

        assert 'first handover keeps' in text

    def test_the_testing_guide_runs_a_packages_frontend_specs_the_same_way(self):
        root = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
        guide = (root / 'docs' / 'MODULE_TESTING_GUIDE.md').read_text(encoding='utf-8')

        assert 'npx vitest run --experimental.fsModuleCache=false' in guide

    def test_claude_md_only_points_at_agents_md(self, package):
        assert (package / 'CLAUDE.md').read_text(encoding='utf-8') == '@AGENTS.md\n'

    def test_the_check_commands_are_the_ones_the_quickstart_names(self, package):
        named = _commands((package / 'AGENTS.md').read_text(encoding='utf-8'))
        documented = _commands(_quickstart())

        assert named, 'the generated AGENTS.md names no command'
        for command in named:
            assert command in documented, (
                f'the quickstart does not name the command the generated '
                f'AGENTS.md gives an agent:\n{command}'
            )

    def test_the_check_commands_run_as_written_in_a_fresh_package(
        self, package, tmp_path
    ):
        prefix = ['docker', 'compose', 'exec', 'backend', 'uv', 'run', 'python']
        commands = _commands((package / 'AGENTS.md').read_text(encoding='utf-8'))
        ran = 0
        for command in commands:
            args = shlex.split(command)
            if args[: len(prefix)] != prefix:
                continue
            args = [
                arg.replace('/modules-workspace', str(tmp_path / 'workspace'))
                for arg in args[len(prefix) :]
            ]
            assert args[0] == 'manage.py', command
            result = CliRunner().invoke(app, args[1:])
            assert result.exit_code == 0, f'{command}\n{result.output}'
            ran += 1

        assert ran, 'no command of the generated AGENTS.md was run'


@pytest.mark.unit
class TestTheQuickstartSaysHowToBuildWithAnAgent:
    def _section(self) -> str:
        document = _quickstart()
        heading = '## Building a module with an AI coding agent'
        assert heading in document, 'the quickstart has no section on agents'
        return document.split(heading, 1)[1].split('\n## ', 1)[0]

    def test_it_says_what_to_give_the_agent_and_how_to_check_the_result(self):
        section = self._section()

        for phrase in (
            'AGENTS.md',
            'CLAUDE.md',
            'module validate',
            'MODULE_TESTING_GUIDE.md',
            'import',
            'catalogs',
            'migration',
        ):
            assert phrase in section, f'the agent section never says {phrase!r}'

    def test_path_a_sends_the_agent_to_the_repositorys_own_rules(self):
        document = _quickstart()
        path_a = document.split('## Path A:', 1)[1].split('## Path B:', 1)[0]

        assert 'AGENTS.md' in path_a
        assert 'backend/AGENTS.md' in path_a
