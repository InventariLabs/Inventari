"""End-to-end regression for the migration crash-loop.

The incident: ``shopping_list_items.template_id`` existed in the database while
``alembic_version_shopping_lists`` still pointed at ``001_initial``. The next
restart ran ``002_item_template``, got ``column already exists``, and the
container looped under ``restart: unless-stopped``.

These tests rebuild that state on a throwaway database and pin the whole
recovery path: the upgrade really does fail, ``db doctor`` names the module and
prints a stamp command, and after the stamp the upgrade completes. Without the
first assertion the suite would still pass if the drift stopped being harmful,
and we would not notice the doctor had become decoration.

The last two classes cover the automatic side: ``BaseModule`` reconciling a
collision without skipping revisions, and the doctor seeing every module that
owns migrations.
"""

import pytest
from sqlalchemy import create_engine, text

from app.core.db_isolation import isolated_db_url
from app.core.migration_doctor import (
    RevisionDDL,
    diagnose_modules,
    has_drift,
    ordered_revisions,
    revision_ddl,
    suggest_stamp_revision,
)
from app.core.module_migrations import (
    discover_modules_with_migrations,
    get_version_table_name,
    run_module_migrations,
)

# The module from the incident: 002 adds a column to a table 001 created, so
# rolling the version back leaves DDL that the pending migration would re-add.
DRIFT_MODULE = 'shopping_lists'


@pytest.fixture
def scratch_db_url():
    """A database of our own — this test rewrites version tables."""
    with isolated_db_url('doctor') as url:
        yield url


@pytest.fixture(autouse=True)
def frozen_modules_root(tmp_path, monkeypatch):
    """Examine a frozen snapshot of the module tree, not the live one.

    ``app/modules`` is one directory shared by every xdist worker, and the
    module-installer fixture in the upgrade tests holds a real ``fixture_*``
    package in an install→teardown window there. A doctor test that
    enumerates the live tree races that window: the module appears in one
    enumeration and not in the other, or its migrations vanish between the
    listing and the read — the suite reports red at random, in both
    directions, and a red full run stops measuring anything.

    Every test in this file therefore examines a snapshot: symlinks to the
    real module directories, taken once, with the ``fixture_*`` sandboxes
    left out. Those names belong to this suite's own installer fixtures and
    are never modules whose crash-loop the doctor must catch; everything
    else keeps its real identity, so a migration run through the snapshot
    still reads the module's actual files.
    """
    import app.core.migration_doctor as migration_doctor
    import app.core.module_migrations as module_migrations

    snapshot = tmp_path / 'modules'
    snapshot.mkdir()
    for entry in module_migrations.MODULES_ROOT.iterdir():
        if entry.name.startswith('fixture_') or not entry.is_dir():
            continue
        (snapshot / entry.name).symlink_to(entry, target_is_directory=True)
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', snapshot)
    monkeypatch.setattr(migration_doctor, 'MODULES_ROOT', snapshot)


def _create_core_tables(db_url: str) -> None:
    """Core schema only — the module's own migrations create its tables."""
    import app.core.template_models
    import app.models  # noqa: F401
    from app.database import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    # Drop what the module owns so its migration chain runs for real.
    with engine.connect() as conn:
        conn.execute(
            text(
                f'DROP TABLE IF EXISTS "{get_version_table_name(DRIFT_MODULE)}" CASCADE'
            )
        )
        for revision in ordered_revisions(DRIFT_MODULE):
            for table in sorted(revision_ddl(revision.path).tables):
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
        conn.commit()
    engine.dispose()


def _rewind_version_table(db_url: str, revision: str) -> None:
    """Point the version table at an older revision, leaving the schema alone."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                f'UPDATE "{get_version_table_name(DRIFT_MODULE)}" '  # module name, not user input
                'SET version_num = :revision'
            ),
            {'revision': revision},
        )
        conn.commit()
    engine.dispose()


@pytest.mark.integration
class TestDriftDetectionAndRepair:
    def test_doctor_detects_and_stamp_module_repairs_mid_chain_drift(
        self, scratch_db_url
    ):
        revisions = ordered_revisions(DRIFT_MODULE)
        assert len(revisions) > 1, f'{DRIFT_MODULE} needs a multi-revision chain'
        rewind_to, ahead = revisions[0].revision, revisions[1]
        assert revision_ddl(ahead.path), f'{ahead.revision} adds no inspectable DDL'

        _create_core_tables(scratch_db_url)
        run_module_migrations(DRIFT_MODULE, 'upgrade', db_url=scratch_db_url)
        _rewind_version_table(scratch_db_url, rewind_to)

        engine = create_engine(scratch_db_url)
        try:
            # 1. The state really is harmful — this is the crash loop.
            with pytest.raises(Exception, match='(?i)already exists'):
                run_module_migrations(DRIFT_MODULE, 'upgrade', db_url=scratch_db_url)

            # 2. The doctor names it and hands over a fix.
            drifted = diagnose_modules(engine, [DRIFT_MODULE])[0]
            assert drifted.status == 'schema_ahead'
            assert has_drift([drifted])
            assert drifted.fix_command
            assert f'stamp-module {DRIFT_MODULE}' in drifted.fix_command

            # 3. The fix works, and the upgrade the deploy wanted goes through.
            with engine.connect() as conn:
                from app.core.migration_doctor import read_schema_state

                target = suggest_stamp_revision(DRIFT_MODULE, read_schema_state(conn))
            assert target and target in drifted.fix_command

            run_module_migrations(
                DRIFT_MODULE, 'stamp', db_url=scratch_db_url, revision=target
            )
            run_module_migrations(DRIFT_MODULE, 'upgrade', db_url=scratch_db_url)

            repaired = diagnose_modules(engine, [DRIFT_MODULE])[0]
            assert repaired.status == 'ok'
            assert not has_drift([repaired])
        finally:
            engine.dispose()

    def test_stamp_module_rewinds_a_database_ahead_of_the_code(self, scratch_db_url):
        """The doctor's fix has to work when the database is newer than the checkout.

        The version table then names a revision this checkout has never heard
        of, and a stamp that first resolves the recorded revision refuses with
        "Can't locate revision" — in exactly the situation the doctor sends the
        operator to it for.
        """
        revisions = ordered_revisions(DRIFT_MODULE)
        _create_core_tables(scratch_db_url)
        run_module_migrations(DRIFT_MODULE, 'upgrade', db_url=scratch_db_url)
        _rewind_version_table(scratch_db_url, '999_from_a_newer_release')

        run_module_migrations(
            DRIFT_MODULE,
            'stamp',
            db_url=scratch_db_url,
            revision=revisions[0].revision,
        )

        engine = create_engine(scratch_db_url)
        try:
            with engine.connect() as conn:
                recorded = (
                    conn.execute(
                        text(
                            f'SELECT version_num FROM "{get_version_table_name(DRIFT_MODULE)}"'
                        )
                    )
                    .scalars()
                    .all()
                )
            assert recorded == [revisions[0].revision]
        finally:
            engine.dispose()

    def test_an_empty_database_is_not_drift(self, scratch_db_url):
        """B3's blocking edge case: the doctor runs before the first migration."""
        engine = create_engine(scratch_db_url)
        try:
            diagnoses = diagnose_modules(engine)

            assert diagnoses, 'no modules discovered'
            assert not has_drift(diagnoses)
            assert {d.status for d in diagnoses} == {'fresh'}
        finally:
            engine.dispose()

    def test_a_fully_migrated_database_is_clean(self, scratch_db_url):
        """The other false-positive risk: healthy state must report no drift."""
        _create_core_tables(scratch_db_url)
        run_module_migrations(DRIFT_MODULE, 'upgrade', db_url=scratch_db_url)

        engine = create_engine(scratch_db_url)
        try:
            diagnosis = diagnose_modules(engine, [DRIFT_MODULE])[0]

            assert diagnosis.status == 'ok'
        finally:
            engine.dispose()


@pytest.mark.integration
class TestReconciliationAfterDuplicateTable:
    """``BaseModule`` must not stamp head just because a table already existed.

    The old handler caught ``DuplicateTable`` and jumped straight to head, so
    every revision after the collision was marked applied without running. A
    module whose 002 adds a column ended up "up to date" with the column
    missing — the API 500s on first use, which is quieter and harder to trace
    than the crash it replaced.
    """

    def test_stamps_the_verified_revision_and_finishes_the_upgrade(
        self, scratch_db_url, monkeypatch
    ):
        from app.core._base_module import BaseModule

        revisions = ordered_revisions(DRIFT_MODULE)
        baseline, ahead = revisions[0].revision, revisions[1]
        column_added = sorted(revision_ddl(ahead.path).columns)
        assert column_added, f'{ahead.revision} adds no column to check'

        _create_core_tables(scratch_db_url)
        run_module_migrations(
            DRIFT_MODULE, 'upgrade', db_url=scratch_db_url, revision=baseline
        )
        engine = create_engine(scratch_db_url)
        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE "{get_version_table_name(DRIFT_MODULE)}"'))
            conn.commit()

        # The helper reads DATABASE_URL, same as run_module_migrations.
        monkeypatch.setenv('DATABASE_URL', scratch_db_url)
        # It only ever uses the module name, never self.
        reconciled = BaseModule._reconcile_existing_schema(None, DRIFT_MODULE)  # type: ignore[arg-type]

        try:
            assert reconciled

            diagnosis = diagnose_modules(engine, [DRIFT_MODULE])[0]
            assert diagnosis.status == 'ok', (
                'reconciliation must finish the upgrade, not just stamp'
            )

            table, column = column_added[0]
            with engine.connect() as conn:
                found = conn.execute(
                    text(
                        'SELECT 1 FROM information_schema.columns '
                        'WHERE table_name = :t AND column_name = :c'
                    ),
                    {'t': table, 'c': column},
                ).scalar()
            assert found, f'{table}.{column} missing — 002 was skipped, not applied'
        finally:
            engine.dispose()

    def test_refuses_to_guess_when_the_schema_shows_nothing(
        self, scratch_db_url, monkeypatch
    ):
        """No DDL to testify about → re-raise instead of inventing a revision."""
        from app.core._base_module import BaseModule

        monkeypatch.setenv('DATABASE_URL', scratch_db_url)

        assert BaseModule._reconcile_existing_schema(None, DRIFT_MODULE) is False  # type: ignore[arg-type]


@pytest.mark.integration
class TestDoctorCoversEveryModule:
    def test_no_module_is_invisible_to_the_doctor(self, scratch_db_url):
        """A module the doctor skips is a module that can crash-loop unnoticed."""
        engine = create_engine(scratch_db_url)
        try:
            diagnosed = {d.module for d in diagnose_modules(engine)}
        finally:
            engine.dispose()

        assert diagnosed == set(discover_modules_with_migrations())

    def test_ddl_reading_finds_something_in_every_chain(self):
        """A chain the doctor can read nothing from cannot be checked for drift."""
        blind: list[str] = []
        for module in discover_modules_with_migrations():
            total = RevisionDDL()
            for revision in ordered_revisions(module):
                total = total | revision_ddl(revision.path)
            if not total:
                blind.append(module)

        assert not blind, f'no readable DDL in: {", ".join(blind)}'
