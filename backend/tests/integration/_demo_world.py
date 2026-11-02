"""A demo organization seeded once per run, put back for every test that reads it.

Seeding a demo organization takes seconds (the ledger, the documents, the
recipes) and the tests that check one detail of it used to pay that price
each. The database is emptied after every test, so a seed cannot simply stay
in it; instead the seed is kept beside the tables and copied in:

* the first worker to ask for a world builds it and writes every table it
  filled — and the files it stored — under the run's shared directory, while
  the others wait on a lock;
* each worker loads that directory once into a schema of its own database;
* each test starts with ``INSERT ... SELECT`` of the schema into the empty
  tables and a copy of the stored files back into the file storage, and
  leaves through the ordinary clean-up, so a test that changes the world
  changes only its own copy.

``restore`` is what a fixture calls; ``tests/integration/conftest.py`` binds
it to the test's session and the run's shared directory as ``demo_world``.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import Session

import tests._db_hygiene as hygiene
from app.cli.commands_demo import apply_demo_onboarding, open_sandbox_account
from app.config import settings
from app.core.file_storage.service import FileStorageService
from app.models.organization import Organization
from app.models.user import User
from app.services.demo_sandbox_service import add_to_pool_async
from app.services.token_service import get_password_hash
from seed_demo_data import SEEDED_MODULES, seed_organization
from seed_demo_showcase import dress_for_visitors
from tests.integration._shelf import run_in_async_session

# The tables each world holds, per key, for the worker that has loaded it.
_loaded: dict[str, list[str]] = {}


def _schema(key: str) -> str:
    return f'world_{key.replace("-", "_")}'


def _storage_root() -> Path | None:
    return getattr(FileStorageService()._provider, 'base_path', None)


def _storage_files() -> dict[str, Path]:
    """The files the suite's file storage holds now, by path inside it."""
    root = _storage_root()
    if root is None:
        return {}
    return {
        str(path.relative_to(root)): path for path in root.rglob('*') if path.is_file()
    }


def _copy_out(db: Session, table: str, target: Path) -> None:
    raw = db.connection().connection
    with raw.cursor() as cursor, target.open('wb') as out:
        cursor.copy_expert(f'COPY {table} TO STDOUT (FORMAT binary)', out)


def _copy_in(db: Session, table: str, source: Path) -> None:
    raw = db.connection().connection
    with raw.cursor() as cursor, source.open('rb') as src:
        cursor.copy_expert(f'COPY {table} FROM STDIN (FORMAT binary)', src)


def _build(db: Session, world: Path, build: Callable[[Session], Any]) -> None:
    """Run *build* on the empty database and keep what it left, then empty it."""
    stored_before = set(_storage_files())
    payload = build(db)
    db.commit()
    tables = hygiene.dirty_tables(db.connection())

    staging = world.with_name(world.name + '.partial')
    shutil.rmtree(staging, ignore_errors=True)
    (staging / 'tables').mkdir(parents=True)
    for table in tables:
        _copy_out(db, table, staging / 'tables' / table)
    for relative, path in _storage_files().items():
        if relative not in stored_before:
            kept = staging / 'files' / relative
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, kept)
    (staging / 'payload.json').write_text(json.dumps(payload, default=str))
    (staging / 'tables.json').write_text(json.dumps(tables))
    staging.rename(world)

    db.expunge_all()
    hygiene.restore_pristine(db.connection())
    db.commit()


def _load(db: Session, world: Path, key: str) -> None:
    """Copy the published world into this worker's database, next to the tables."""
    tables = json.loads((world / 'tables.json').read_text())
    schema = _schema(key)
    db.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
    db.execute(text(f'CREATE SCHEMA {schema}'))
    for table in tables:
        db.execute(text(f'CREATE TABLE {schema}.{table} (LIKE public.{table})'))
        _copy_in(db, f'{schema}.{table}', world / 'tables' / table)
    db.commit()

    _loaded[key] = tables


def _put_files(world: Path) -> None:
    """Give the file storage back every file the world stored, as it was built.

    A test may delete or overwrite a cover, and the clean-up does not touch
    the storage, so the files come back with the rows, for every test.
    """
    root = _storage_root()
    if root is None or not (world / 'files').is_dir():
        return
    for source in (world / 'files').rglob('*'):
        if source.is_file():
            target = root / source.relative_to(world / 'files')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _put_back(db: Session, world: Path, key: str) -> None:
    schema = _schema(key)
    tables = _loaded[key]
    # The system-data tables are not empty: the world holds its own version of
    # them (the seed adds units and categories), which replaces theirs.
    held = [table for table in tables if table in hygiene.SEED_TABLES]
    if hygiene.may_skip_constraints():
        statements = ['SET LOCAL session_replication_role = replica']
        statements += [f'DELETE FROM {table}' for table in held]
        statements += [
            f'INSERT INTO {table} SELECT * FROM {schema}.{table}' for table in tables
        ]
        statements.append('SET LOCAL session_replication_role = DEFAULT')
        db.execute(text('; '.join(statements)))
    else:
        if held:
            db.execute(text(hygiene.clear_statement(held)))
        inserts = ', '.join(
            f'i{n} AS (INSERT INTO {table} SELECT * FROM {schema}.{table})'
            for n, table in enumerate(tables)
        )
        db.execute(text(f'WITH {inserts} SELECT 1'))
    db.commit()
    _put_files(world)


def restore(
    db: Session, shared: Path, key: str, build: Callable[[Session], Any]
) -> Any:
    """Put the world named *key* into the empty database; return what *build* returned.

    *build* runs once per test run, on whichever worker asks first, and must
    leave everything the world is made of in the database or the file storage.
    What it returns has to survive a trip through JSON (ids as strings).
    """
    leftover = hygiene.dirty_tables(db.connection())
    if leftover:
        raise RuntimeError(
            f'the demo world goes into an empty database, and {leftover} already '
            'hold rows: ask for it before anything else writes.'
        )
    world = shared / key
    if key not in _loaded:
        shared.mkdir(parents=True, exist_ok=True)
        with (shared / f'{key}.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not world.exists():
                _build(db, world, build)
        _load(db, world, key)
    _put_back(db, world, key)
    return json.loads((world / 'payload.json').read_text())


def ids(payload: list[str]) -> tuple[uuid.UUID, ...]:
    """The ids a build returned as strings, as ids again."""
    return tuple(uuid.UUID(value) for value in payload)


def seeded_organization(
    *, items: int, dress: bool = False
) -> Callable[[Session], list[str]]:
    """A build for the demo organization the suite reads: seeded, and perhaps dressed.

    The organization has every module the seed fills (and approvals, which the
    dressed demo uses) and an administrator; the build returns their ids.
    """

    def build(db: Session) -> list[str]:
        org = Organization(
            id=uuid.uuid4(),
            name='My Organization',
            enabled_modules=sorted(
                {
                    'core',
                    'items',
                    'locations',
                    'categories',
                    'stats',
                    'approvals',
                    *SEEDED_MODULES,
                }
            ),
        )
        admin = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            email=f'demo-admin+{uuid.uuid4().hex[:8]}@example.com',
            full_name='Demo Administrator',
            hashed_password=get_password_hash('demo-test-password'),
            role='admin',
            is_active=True,
        )
        db.add(org)
        db.commit()
        db.add(admin)
        db.commit()
        seed_organization(db, org.id, admin.id, items=items)
        if dress:
            dress_for_visitors(db, org.id, admin.id)
        return [str(org.id), str(admin.id)]

    return build


def pooled_sandboxes(async_engine: Any) -> Callable[[Session], list[list[str]]]:
    """A build for two sandboxes made the way ``demo fill-pool`` makes one.

    The order is the pool's own -- open, onboard (profile, modules), seed,
    dress, offer -- because the sandbox a visitor receives is the product of
    that order. Each pair is an organization and its administrator, who waits
    inactive on the pool until a visitor takes the sandbox.
    """

    def build(db: Session) -> list[list[str]]:
        opened = []
        with patch.object(settings, 'INVENTARI_DEMO', True):
            for _ in range(2):
                org_id, user_id, email = open_sandbox_account(db)
                run_in_async_session(
                    async_engine,
                    lambda adb, address=email: apply_demo_onboarding(adb, address),
                )
                # The onboarding was written through another session than this one.
                db.expire_all()
                seed_organization(db, org_id, user_id, items=60)
                dress_for_visitors(db, org_id, user_id)
                run_in_async_session(
                    async_engine,
                    lambda adb, org=org_id, admin=user_id: add_to_pool_async(
                        adb, org, admin
                    ),
                )
                opened.append([str(org_id), str(user_id)])
        return opened

    return build
