"""An uninstall removes code. Removing data is a second, separate answer.

The default ``on_uninstall`` hook downgrades the module's migrations to
base, which is ``DROP TABLE`` on every table the module owns, holding
every organization's rows. Uninstall ran it unconditionally, behind a
prompt that spoke only about files: "This will permanently delete all
files for module 'x'. Continue?" — answering yes to a question about
files dropped the tables.

So the hook now runs only for ``--drop-data``, and that flag is not a
y/N: it asks for a word that cannot be hit by reflex.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console
from sqlalchemy.exc import OperationalError

from app.cli import _module_meta, module_packaging


def _tracked_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stub_report: bool
) -> str:
    """One tracked community module with a backend on disk."""
    name = 'fixture_mod'
    backend_root = tmp_path / 'backend_modules'
    frontend_root = tmp_path / 'frontend_modules'
    (backend_root / name).mkdir(parents=True)
    (backend_root / name / 'module.py').write_text('', encoding='utf-8')
    (frontend_root / name).mkdir(parents=True)

    tracking = tmp_path / 'tracking.json'
    tracking.write_text(
        json.dumps(
            {
                'modules': {
                    name: {
                        'version': '0.1.0',
                        'source': './pkg',
                        'has_backend': True,
                        'has_frontend': True,
                        'declares_frontend': True,
                        'requires': [],
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tracking)
    monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', backend_root)
    # The orphan report reads the module's own files for its table names.
    monkeypatch.setattr(_module_meta, 'BACKEND_MODULES_DIR', backend_root)
    monkeypatch.setattr(module_packaging, 'FRONTEND_MODULES_DIR', frontend_root)
    if stub_report:
        # The report and the installation record both talk to the database;
        # neither is what most of these tests are about.
        monkeypatch.setattr(
            module_packaging, '_print_orphan_report', lambda *a, **k: None
        )
    monkeypatch.setattr(
        module_packaging, '_forget_installation_record', lambda *a, **k: None
    )
    return name


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    return _tracked_module(tmp_path, monkeypatch, stub_report=True)


@pytest.fixture
def installed_reporting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """The same install, with the orphan report left as the operator sees it."""
    return _tracked_module(tmp_path, monkeypatch, stub_report=False)


def _capturing_console(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """Swap the packaging console for one writing into a buffer."""
    buffer = io.StringIO()
    monkeypatch.setattr(module_packaging, 'console', Console(file=buffer, width=240))
    return buffer


class _EmptyResult:
    def scalar(self):
        return None


class _EmptyDatabase:
    """A session-shaped object every probe reads as an empty database.

    The probes only ask whether a table exists and how many rows it
    holds; both come back empty from this, which is what a module that
    stored nothing looks like when the database answers.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, *args, **kwargs):
        return _EmptyResult()

    def rollback(self):
        pass


def _watch_hook(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ran: list[str] = []

    def fake_hook(name: str) -> bool:
        ran.append(name)
        return True  # the real hook reports whether it ran; this one ran

    monkeypatch.setattr(module_packaging, '_run_on_uninstall_hook', fake_hook)
    return ran


class TestTheDefaultUninstall:
    def test_the_schema_hook_does_not_run(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        ran = _watch_hook(monkeypatch)

        module_packaging.uninstall_module(installed, force=True)

        assert ran == []

    def test_the_files_are_still_removed(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        _watch_hook(monkeypatch)

        module_packaging.uninstall_module(installed, force=True)

        assert not (module_packaging.BACKEND_MODULES_DIR / installed).exists()
        assert installed not in _module_meta._load_tracking()

    def test_the_prompt_says_the_data_is_kept(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        asked: list[str] = []
        monkeypatch.setattr('typer.confirm', lambda text: asked.append(text) or True)
        _watch_hook(monkeypatch)

        module_packaging.uninstall_module(installed)

        assert len(asked) == 1
        assert 'data will be kept' in asked[0]


class TestAnUncheckedReportIsNotAnEmptyOne:
    """The report is the operator's only view of what is at stake.

    Before answering the prompt the operator reads one line: whether the
    module left stored data behind. A database the command cannot reach
    collapsed into an empty group list, and that same line then said "No
    stored data was found" — the opposite of what a failed probe means.
    """

    def test_a_database_that_cannot_be_opened_is_not_reported_as_empty(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        buffer = _capturing_console(monkeypatch)

        def database_is_down():
            raise OperationalError('SELECT 1', {}, Exception('connection refused'))

        monkeypatch.setattr('app.database.SessionLocal', database_is_down)

        module_packaging.uninstall_module(installed_reporting, force=True)

        output = buffer.getvalue()
        assert "Could not check what module 'fixture_mod' leaves behind" in output
        assert 'No stored data was found' not in output

    def test_a_failed_probe_inside_a_readable_database_says_the_same(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('app.database.SessionLocal', _EmptyDatabase)

        def failing_probe(db, name):
            raise OperationalError(
                'SELECT to_regclass(:t)', {'t': name}, Exception('permission denied')
            )

        monkeypatch.setattr('app.cli._module_orphans._own_tables_group', failing_probe)
        monkeypatch.setattr('app.cli._module_orphans._file_group', lambda name: None)

        module_packaging.uninstall_module(installed_reporting, force=True)

        output = buffer.getvalue()
        assert "Could not check what module 'fixture_mod' leaves behind" in output
        assert 'No stored data was found' not in output

    def test_a_partial_report_keeps_what_it_counted_and_says_it_is_incomplete(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        from app.cli._module_orphans import OrphanGroup

        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('app.database.SessionLocal', _EmptyDatabase)
        monkeypatch.setattr('app.cli._module_orphans._file_group', lambda name: None)
        monkeypatch.setattr(
            'app.cli._module_orphans._enabled_group',
            lambda db, name: OrphanGroup(
                label='organizations still listing the module as enabled',
                singular='organization still listing the module as enabled',
                count=1,
                where='organizations.enabled_modules',
            ),
        )

        def failing_probe(db, name):
            raise OperationalError(
                'SELECT to_regclass(:t)', {'t': name}, Exception('permission denied')
            )

        monkeypatch.setattr('app.cli._module_orphans._own_tables_group', failing_probe)

        module_packaging.uninstall_module(installed_reporting, force=True)

        output = buffer.getvalue()
        assert "Could not check what module 'fixture_mod' leaves behind" in output
        assert 'The list below is incomplete.' in output
        assert '1 organization still listing the module as enabled' in output
        assert 'No stored data was found' not in output

    def test_a_complete_report_with_nothing_found_still_says_so(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins the honest path; the old code says this too, so it only
        documents that the fix did not silence a truthful line."""
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('app.database.SessionLocal', _EmptyDatabase)
        monkeypatch.setattr('app.cli._module_orphans._file_group', lambda name: None)

        module_packaging.uninstall_module(installed_reporting, force=True)

        assert "No stored data was found for module 'fixture_mod'." in buffer.getvalue()

    def test_a_module_file_that_cannot_be_read_is_not_reported_as_empty(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The table names come from the module's own source; a file that
        will not parse names none, and the report went on to say nothing
        was stored — about tables it had never looked for."""
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('app.database.SessionLocal', _EmptyDatabase)
        monkeypatch.setattr('app.cli._module_orphans._file_group', lambda name: None)
        models = (
            module_packaging.BACKEND_MODULES_DIR / installed_reporting / 'models.py'
        )
        models.write_text(
            "class Recipe:\n    __tablename__ = 'fixture_mod_recipes'\n    def (\n",
            encoding='utf-8',
        )

        module_packaging.uninstall_module(installed_reporting, force=True)

        output = buffer.getvalue()
        assert "Could not check what module 'fixture_mod' leaves behind" in output
        assert 'cannot read tables from' in output
        assert 'models.py' in output
        assert 'No stored data was found' not in output

    def test_a_readable_module_whose_tables_are_absent_is_still_empty(
        self, installed_reporting: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins the honest path next to the one above: the walk read every
        file and named a table, and the database does not hold it."""
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('app.database.SessionLocal', _EmptyDatabase)
        monkeypatch.setattr('app.cli._module_orphans._file_group', lambda name: None)
        models = (
            module_packaging.BACKEND_MODULES_DIR / installed_reporting / 'models.py'
        )
        models.write_text(
            "class Recipe:\n    __tablename__ = 'fixture_mod_recipes'\n",
            encoding='utf-8',
        )

        module_packaging.uninstall_module(installed_reporting, force=True)

        output = buffer.getvalue()
        assert "No stored data was found for module 'fixture_mod'." in output
        assert 'Could not check' not in output


class TestDropData:
    def test_the_report_does_not_say_the_rows_it_destroys_are_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from app.cli import _module_orphans
        from app.cli._module_orphans import OrphanGroup, OrphanReport

        group = OrphanGroup(
            label="rows in the module's own tables",
            singular="row in the module's own tables",
            goes_with_drop_data=True,
            count=1,
            where='kept as they are; fixture_rows',
            where_dropped='dropped with the tables; fixture_rows',
        )
        monkeypatch.setattr(
            _module_orphans, 'collect_orphans', lambda name: OrphanReport((group,))
        )
        buffer = _capturing_console(monkeypatch)

        module_packaging._print_orphan_report('fixture_mod', drop_data=True)

        output = buffer.getvalue()
        assert '--drop-data will destroy' in output
        assert 'dropped with the tables; fixture_rows' in output
        assert 'kept as they are' not in output

        buffer.truncate(0)
        buffer.seek(0)
        module_packaging._print_orphan_report('fixture_mod', drop_data=False)

        assert 'kept as they are; fixture_rows' in buffer.getvalue()

    def test_the_word_data_confirms(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        ran = _watch_hook(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')

        module_packaging.uninstall_module(installed, drop_data=True)

        assert ran == [installed]

    def test_yes_is_not_the_word(self, installed: str, monkeypatch: pytest.MonkeyPatch):
        ran = _watch_hook(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'yes')

        with pytest.raises(SystemExit) as exc:
            module_packaging.uninstall_module(installed, drop_data=True)

        assert exc.value.code == 0
        assert ran == []
        # Cancelled means nothing happened, files included.
        assert (module_packaging.BACKEND_MODULES_DIR / installed).exists()
        assert installed in _module_meta._load_tracking()

    def test_force_skips_the_question_and_drops(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        ran = _watch_hook(monkeypatch)
        monkeypatch.setattr(
            'typer.prompt',
            lambda text: pytest.fail('--force should not ask'),
        )

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        assert ran == [installed]


class TestTheInstallationRecord:
    def test_it_is_cleared_so_a_reinstall_installs(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Left behind, it makes the next install a no-op.

        ``check_module_version_async`` runs ``on_install`` only when there
        is no row for the module. A row surviving the uninstall means a
        reinstall of the same version runs no install hook — no seed, no
        defaults — while the entrypoint recreates the tables, so the
        module comes back looking installed and behaving like it never was.
        """
        forgotten: list[str] = []
        monkeypatch.setattr(
            module_packaging,
            '_forget_installation_record',
            lambda name: forgotten.append(name),
        )
        _watch_hook(monkeypatch)

        module_packaging.uninstall_module(installed, force=True)

        assert forgotten == [installed]


class TestForceNamesWhatItSkips:
    def test_the_bypass_is_named_in_the_output(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """--force --drop-data skips the type-'data' gate; the operator
        must read, before anything is removed, that this is what force
        means — not discover it from a post-facto summary line."""
        buffer = _capturing_console(monkeypatch)
        _watch_hook(monkeypatch)

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        joined = buffer.getvalue()
        assert '--force' in joined
        assert 'DROP' in joined

    def test_the_help_names_the_data_gate(self):
        """The documented meaning of --force names the data gate it
        skips, not a vague 'confirmation prompt'."""
        import click
        from typer.testing import CliRunner

        from app.cli.commands_module import module_app

        result = CliRunner().invoke(module_app, ['uninstall', '--help'])

        assert result.exit_code == 0
        # Typer forces a colour terminal when GITHUB_ACTIONS, FORCE_COLOR or
        # PY_COLORS is set, and the escape codes then cut '--drop-data' into
        # separately styled pieces. The reader sees the text, so the
        # assertions read the text.
        help_text = click.unstyle(result.output)
        assert '--drop-data' in help_text
        # The --force line itself must name the gate: a vague "skip
        # confirmation prompts" passed this test while the neighbouring
        # --drop-data line supplied the word "data".
        force_lines = [line for line in help_text.splitlines() if '--force' in line]
        assert force_lines, 'no --force line in the help output'
        assert any('data' in line.lower() for line in force_lines), (
            f'--force help does not name the data gate: {force_lines}'
        )


class TestTheDropMessageTellsTheTruth:
    def test_no_backend_files_means_tables_were_not_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A tracking entry whose backend files are already gone has no
        hook to run, so no table was touched — and the summary used to
        say they were dropped anyway."""
        buffer = _capturing_console(monkeypatch)

        name = 'ghost_mod'
        backend_root = tmp_path / 'backend_modules'
        frontend_root = tmp_path / 'frontend_modules'
        frontend_root.mkdir(parents=True)
        # No backend dir at all — the corner the review measured.
        tracking = tmp_path / 'tracking.json'
        tracking.write_text(
            json.dumps(
                {
                    'modules': {
                        name: {
                            'version': '0.1.0',
                            'source': './pkg',
                            'has_backend': True,
                            'has_frontend': False,
                            'declares_frontend': False,
                            'requires': [],
                        }
                    }
                }
            ),
            encoding='utf-8',
        )
        monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tracking)
        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', backend_root)
        monkeypatch.setattr(module_packaging, 'FRONTEND_MODULES_DIR', frontend_root)
        monkeypatch.setattr(
            module_packaging, '_print_orphan_report', lambda *a, **k: None
        )
        monkeypatch.setattr(
            module_packaging, '_forget_installation_record', lambda *a, **k: None
        )
        ran = _watch_hook(monkeypatch)

        module_packaging.uninstall_module(name, force=True, drop_data=True)

        assert ran == []  # no files, no hook, no drop
        joined = buffer.getvalue()
        assert 'Its tables and their data were dropped' not in joined
        assert 'were not' in joined or 'left in place' in joined

    def test_the_normal_drop_path_still_says_dropped(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The honest shape: the module names its tables, the hook runs,
        the schema confirms the named set is gone — the summary keeps
        saying so. The tables must be nameable for the claim to exist at
        all; a drop of an unnamed set reads as unverified instead."""
        (module_packaging.BACKEND_MODULES_DIR / installed / 'models.py').write_text(
            "class Thing:\n    __tablename__ = 'fixture_mod_thing'\n",
            encoding='utf-8',
        )
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')
        _watch_hook(monkeypatch)

        class _SchemaWithNothingLeft:
            def get_table_names(self):
                return []

        monkeypatch.setattr(
            'sqlalchemy.inspect', lambda *a, **k: _SchemaWithNothingLeft()
        )
        monkeypatch.setattr(
            'app.cli.commands_db._migration_db_url',
            lambda: 'postgresql://irrelevant',
        )

        module_packaging.uninstall_module(installed, drop_data=True)

        assert 'Its tables and their data were dropped' in buffer.getvalue()

    def test_a_hook_that_never_ran_never_claims_a_drop(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The files are on disk but the module never made it into the
        registry (a rejected import), so the drop-hook could not run and
        the tables are still in the database. The summary used to say
        they were dropped — contradicting the database two lines below
        the promise."""
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')

        def hook_that_was_skipped(name: str) -> bool:
            return False  # the registry had no such module

        monkeypatch.setattr(
            module_packaging, '_run_on_uninstall_hook', hook_that_was_skipped
        )

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        output = buffer.getvalue()
        assert 'were dropped' not in output
        assert 'were NOT dropped' in output
        assert 'uninstall it again' in output

    def test_a_hook_that_ran_but_dropped_nothing_does_not_claim_a_drop(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """A module with no migrations directory skips its downgrade
        quietly, and an empty ``downgrade()`` drops nothing — both hooks
        return clean, so "the hook ran" says nothing about the tables.
        The schema is the one witness that cannot be fooled: the summary
        asks it and names every table still standing."""
        (module_packaging.BACKEND_MODULES_DIR / installed / 'models.py').write_text(
            "class Thing:\n    __tablename__ = 'fixture_mod_thing'\n",
            encoding='utf-8',
        )
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')
        _watch_hook(monkeypatch)  # ran, and ran without an exception

        class _SchemaStillHoldingTheTables:
            def get_table_names(self):
                return ['fixture_mod_thing', 'fixture_mod_leftover']

        monkeypatch.setattr(
            'sqlalchemy.inspect', lambda *a, **k: _SchemaStillHoldingTheTables()
        )
        monkeypatch.setattr(
            'app.cli.commands_db._migration_db_url',
            lambda: 'postgresql://irrelevant',
        )

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        output = buffer.getvalue()
        assert 'were dropped' not in output, (
            'the schema still holds the tables; the summary must not claim the drop'
        )
        assert 'still in the database' in output
        assert 'fixture_mod_thing' in output, 'the leftovers are named'

    def test_an_unnameable_table_set_withholds_the_claim(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The collector reads ``__tablename__`` and ``create_table`` — a
        module whose tables are made any other way owns tables the summary
        cannot name. "Dropped" about a set nobody could list is the old
        lie wearing a new hat: the hook ran clean, the schema says the
        named set is empty, and that verifies nothing about the tables
        that were never named. The claim stays unspoken."""
        # No models.py, no migrations: the collector has nothing to read.
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')
        _watch_hook(monkeypatch)  # ran, and ran without an exception

        class _SchemaWithNothingLeft:
            def get_table_names(self):
                return []

        monkeypatch.setattr(
            'sqlalchemy.inspect', lambda *a, **k: _SchemaWithNothingLeft()
        )
        monkeypatch.setattr(
            'app.cli.commands_db._migration_db_url',
            lambda: 'postgresql://irrelevant',
        )

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        output = buffer.getvalue()
        assert 'were dropped' not in output, (
            'no table was ever named; nothing here verifies a drop'
        )
        assert 'unverified' in output

    def test_a_verified_drop_still_says_dropped(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The schema check exists to silence a false claim, not the true
        one: when the database confirms the tables are gone, the summary
        keeps saying so. Passes on the old code too — it pins the honest
        path, it does not discriminate."""
        (module_packaging.BACKEND_MODULES_DIR / installed / 'models.py').write_text(
            "class Thing:\n    __tablename__ = 'fixture_mod_thing'\n",
            encoding='utf-8',
        )
        buffer = _capturing_console(monkeypatch)
        monkeypatch.setattr('typer.prompt', lambda text: 'data')
        _watch_hook(monkeypatch)

        class _SchemaWithNothingLeft:
            def get_table_names(self):
                return []

        monkeypatch.setattr(
            'sqlalchemy.inspect', lambda *a, **k: _SchemaWithNothingLeft()
        )
        monkeypatch.setattr(
            'app.cli.commands_db._migration_db_url',
            lambda: 'postgresql://irrelevant',
        )

        module_packaging.uninstall_module(installed, force=True, drop_data=True)

        assert 'Its tables and their data were dropped' in buffer.getvalue()

    def test_a_missing_registry_entry_skips_the_hook(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The registry check lives in the hook itself: a module the
        registry cannot name means the hook does not run — that is the
        false the summary must not print."""
        buffer = _capturing_console(monkeypatch)

        class _RegistryWithoutTheModule:
            def get(self, name: str):
                return None

        monkeypatch.setattr(
            'app.core.module_registry.module_registry',
            _RegistryWithoutTheModule(),
        )

        assert module_packaging._run_on_uninstall_hook(installed) is False
        assert 'skipping on_uninstall hook' in buffer.getvalue()


class TestANonWritableCheckout:
    def test_uninstall_stops_before_the_data_drop_and_the_removal(
        self, installed: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The code lives in a checkout the container's user may no longer be
        # able to write; deleting a file entry needs write access to the
        # directory that holds it. Refuse before on_uninstall runs, or a
        # --drop-data uninstall drops the tables and then cannot remove the
        # code the record still claims is installed.
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        monkeypatch.setattr(module_packaging.os, 'access', lambda *_a: False)
        buffer = _capturing_console(monkeypatch)
        ran = _watch_hook(monkeypatch)

        with pytest.raises(SystemExit):
            module_packaging.uninstall_module(installed, force=True, drop_data=True)

        assert _module_meta.module_tree_permissions_command() in buffer.getvalue()
        assert ran == []
        assert (module_packaging.BACKEND_MODULES_DIR / installed).exists()
