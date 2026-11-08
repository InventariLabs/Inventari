"""Tests for the Inventari CLI (manage.py)."""

import sys
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from manage import app

runner = CliRunner()


class TestHelp:
    """Test that --help works for all command groups."""

    def test_main_help(self):
        result = runner.invoke(app, ['--help'])
        assert result.exit_code == 0
        assert 'db' in result.output
        assert 'user' in result.output
        assert 'module' in result.output
        assert 'arch' in result.output
        assert 'shell' in result.output

    def test_db_help(self):
        result = runner.invoke(app, ['db', '--help'])
        assert result.exit_code == 0
        assert 'reset' in result.output
        assert 'seed' in result.output
        assert 'upgrade' in result.output
        assert 'downgrade' in result.output
        assert 'migrate' in result.output

    def test_user_help(self):
        result = runner.invoke(app, ['user', '--help'])
        assert result.exit_code == 0
        assert 'create-admin' in result.output

    def test_module_help(self):
        result = runner.invoke(app, ['module', '--help'])
        assert result.exit_code == 0
        assert 'create' in result.output
        assert 'validate' in result.output
        assert 'list' in result.output

    def test_the_language_option_names_every_language_the_scaffold_takes(self):
        """The help listed four languages while the scaffold took five: pt was
        accepted and never offered."""
        import re

        from app.i18n import SUPPORTED_LANGUAGES

        result = runner.invoke(
            app, ['module', 'new-community', '--help'], env={'COLUMNS': '400'}
        )
        listed = re.search(r'catalog for \(([^)]*)\)', result.output)

        assert result.exit_code == 0
        assert listed is not None, result.output
        assert listed.group(1).split(', ') == [
            lang for lang in SUPPORTED_LANGUAGES if lang != 'en'
        ]

    def test_arch_help(self):
        result = runner.invoke(app, ['arch', '--help'])
        assert result.exit_code == 0
        assert 'lint' in result.output


class TestDbReset:
    """Test db reset command safety mechanisms."""

    def test_blocked_in_production(self, monkeypatch):
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        result = runner.invoke(app, ['db', 'reset'])
        assert result.exit_code == 1
        assert "'production'" in result.output

    def test_blocked_in_prod_shorthand(self, monkeypatch):
        monkeypatch.setenv('INVENTARI_ENV', 'prod')
        result = runner.invoke(app, ['db', 'reset'])
        assert result.exit_code == 1

    def test_yes_i_am_sure_still_blocked_in_production(self, monkeypatch):
        """--yes-i-am-sure skips the prompt but does NOT bypass the install check."""
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        result = runner.invoke(app, ['db', 'reset', '--yes-i-am-sure'])
        assert result.exit_code == 1
        assert "'production'" in result.output

    def test_requires_database_url(self, monkeypatch):
        monkeypatch.setenv('INVENTARI_ENV', 'development')
        monkeypatch.delenv('DATABASE_URL', raising=False)
        result = runner.invoke(app, ['db', 'reset'])
        assert result.exit_code == 1
        assert 'DATABASE_URL' in result.output

    def test_requires_confirmation(self, monkeypatch):
        monkeypatch.setenv('INVENTARI_ENV', 'development')
        monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@localhost/testdb')
        result = runner.invoke(app, ['db', 'reset'], input='wrong_name\n')
        assert result.exit_code == 1
        assert 'Confirmation failed' in result.output


class TestDbDowngrade:
    """Test db downgrade production safety."""

    def test_blocked_in_production(self, monkeypatch):
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        result = runner.invoke(app, ['db', 'downgrade', 'abc123'])
        assert result.exit_code == 1
        assert "'production'" in result.output

    def test_missing_revision_argument(self):
        result = runner.invoke(app, ['db', 'downgrade'])
        assert result.exit_code == 2  # Typer requires the revision argument


class TestModuleCreate:
    """Test module create command."""

    def test_module_create_calls_generator(self):
        """module create delegates to module_generator.create_module()."""
        with patch('app.cli.module_generator.create_module') as mock_create:
            result = runner.invoke(app, ['module', 'create', 'my_test_module'])
        assert result.exit_code == 0
        mock_create.assert_called_once_with('my_test_module')


class TestModuleValidate:
    """Test module validate command."""

    def test_validate_nonexistent_path_fails(self):
        """Pointing to a non-existent path exits with code 1."""
        result = runner.invoke(
            app, ['module', 'validate', '--base-path', 'nonexistent/path']
        )
        assert result.exit_code == 1

    def test_validate_existing_modules_pass(self):
        """All bundled modules should pass validation."""
        result = runner.invoke(app, ['module', 'validate'])
        assert result.exit_code == 0


class TestArchLint:
    """``arch lint`` hands its options to the lint and answers with its verdict.

    What the lint finds in the real tree is the lint's own business: ``make
    lint`` and the commit hook run it whole-tree, and its tests run it on a
    copy of its own. A whole-tree run is tens of seconds of one worker.
    """

    @pytest.mark.parametrize('verdict', [0, 1])
    def test_arch_lint_exits_with_the_verdict_of_the_lint(self, monkeypatch, verdict):
        argv_seen = []

        def lint():
            argv_seen.append(list(sys.argv))
            return verdict

        monkeypatch.setattr('app.core.architecture_lint.main', lint)

        result = runner.invoke(app, ['arch', 'lint', '--quiet'])

        assert result.exit_code == verdict
        assert argv_seen == [['architecture_lint', '--quiet']]


class TestShell:
    """Test shell command registration."""

    def test_shell_registered(self):
        """shell command should be registered and show help without error."""
        result = runner.invoke(app, ['shell', '--help'])
        assert result.exit_code == 0


class TestModuleList:
    """Test module list command."""

    def test_module_list_runs(self):
        result = runner.invoke(app, ['module', 'list'])
        assert result.exit_code == 0
