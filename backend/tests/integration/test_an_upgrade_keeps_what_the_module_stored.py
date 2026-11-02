"""Going from v0.1 to v0.2 without losing the tenants' data.

There was no route between two versions of a community module. The
install guard refused to install over a tracked module and said "Run
module uninstall first", and the uninstall it pointed at ran the module's
default ``on_uninstall`` — an Alembic downgrade to base, which is
``DROP TABLE`` on everything the module owns, for every organization on
the installation. So the documented upgrade path destroyed the data it
was upgrading.

This exercises the real command against a real package: install v0.1,
store a row the way a tenant would, upgrade to a v0.2 that ships another
migration, and look at what is in the table afterwards.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app import modules as app_modules
from app.cli import _module_meta, _module_upgrade, module_packaging
from app.cli._module_upgrade import upgrade_module
from app.cli.module_packaging import install_module
from app.config import settings
from app.core import module_migrations
from app.core.module_migrations import run_module_migrations

pytestmark = [pytest.mark.integration]

# The tree every xdist worker can see. Nothing this file installs may land
# here: the migration doctor enumerates it, and a fixture module is a module
# the other worker has no way to tell from a real one.
SHARED_MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'

_MODELS = """\
import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Claim(Base):
    __tablename__ = '{table}'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    note: Mapped[str] = mapped_column(String(200))
"""

_ENV = """\
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from app.modules.{name}.models import Base  # noqa: E402

target_metadata = Base.metadata
VERSION_TABLE = 'alembic_version_{name}'


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {{}}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
"""

_MIGRATION_001 = """\
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        '{table}',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('{table}')
"""

_MIGRATION_002 = """\
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_status'
down_revision: str | None = '001_initial'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        '{table}',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
    )


def downgrade() -> None:
    op.drop_column('{table}', 'status')
"""


def _write_package(
    root: Path, name: str, table: str, version: str, *, with_status: bool
) -> Path:
    """Write a minimal but genuine community module package."""
    pkg = root / f'{name}-{version}'
    backend = pkg / 'backend'
    (backend / 'migrations' / 'versions').mkdir(parents=True, exist_ok=True)
    (backend / 'i18n').mkdir(parents=True, exist_ok=True)

    (pkg / 'module.yaml').write_text(
        f'name: {name}\n'
        f'version: "{version}"\n'
        'inventari_min_version: "0.9.0"\n'
        'author: "Test"\n'
        'description: "Fixture module."\n'
        'license: "AGPL-3.0"\n'
        'homepage: "https://example.com"\n'
        'requires: []\n'
        'components:\n'
        '  backend: true\n'
        '  frontend: false\n',
        encoding='utf-8',
    )
    (backend / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': version,
                'display_name': 'Fixture',
                'module_type': 'community',
                'capabilities': ['database'],
            },
            indent=2,
        ),
        encoding='utf-8',
    )
    (backend / '__init__.py').write_text('', encoding='utf-8')
    (backend / 'i18n' / 'en.json').write_text('{}\n', encoding='utf-8')
    (backend / 'router.py').write_text(
        'from fastapi import APIRouter\n\nrouter = APIRouter()\n', encoding='utf-8'
    )
    (backend / 'module.py').write_text(
        'from app.core.module_sdk import define_module\n\n'
        'from .router import router\n\n'
        'module = define_module(router=router)\n',
        encoding='utf-8',
    )
    (backend / 'models.py').write_text(_MODELS.format(table=table), encoding='utf-8')
    (backend / 'migrations' / 'env.py').write_text(
        _ENV.format(name=name), encoding='utf-8'
    )
    (backend / 'migrations' / 'versions' / '001_initial.py').write_text(
        _MIGRATION_001.format(table=table), encoding='utf-8'
    )
    if with_status:
        (backend / 'migrations' / 'versions' / '002_status.py').write_text(
            _MIGRATION_002.format(table=table), encoding='utf-8'
        )
    else:
        # Only v0.1 ships this. v0.2 dropping it is how the test sees
        # whether an upgrade replaces the tree or merely copies over it.
        (backend / 'legacy.py').write_text('LEGACY = True\n', encoding='utf-8')
    return pkg


@pytest.fixture
def fixture_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup_test_db):
    """A community module installed at v0.1, into a tree of this test's own.

    The install used to land in the real ``app/modules`` tree, because that is
    where the migration runner and the import in ``env.py`` look. That tree is
    also what every other xdist worker reads, so the fixture was a module the
    migration doctor enumerated mid-run: ``test_migration_doctor_drift`` went
    red in both directions of the window, depending on which worker won.

    For the duration of the test every writer and reader of the tree is
    pointed at ``tmp_path/modules``: the install and upgrade destinations, the
    tracking file, and the runner. The test's own tree joins ``app.modules`` for
    the length of the test, because the generated ``env.py`` imports
    ``app.modules.<name>.models`` like a real package's does. The name still
    carries a uuid — this file's own tests run in parallel with each other.

    ``setup_test_db`` is requested only for its side effect: the worker's
    database is created there, and a worker whose first test is one of this
    file's would otherwise migrate a database that does not exist yet.
    """
    name = f'fixture_{uuid.uuid4().hex[:8]}'
    table = f'{name}_claims'
    modules_root = tmp_path / 'modules'
    modules_root.mkdir()

    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    # The migration runner reads DATABASE_URL from the environment; this
    # worker's database is the one the assertions read back.
    monkeypatch.setenv('DATABASE_URL', settings.DATABASE_URL)
    for module in (module_packaging, _module_upgrade, _module_meta):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', modules_root)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', tmp_path / 'frontend')
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', modules_root)
    monkeypatch.setattr(
        app_modules, '__path__', [*app_modules.__path__, str(modules_root)]
    )

    v1 = _write_package(tmp_path, name, table, '0.1.0', with_status=False)
    install_module(str(v1), allow_unsigned=True)
    run_module_migrations(name, 'upgrade', db_url=settings.DATABASE_URL)

    try:
        yield name, table, tmp_path, modules_root
    finally:
        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
            conn.execute(text(f'DROP TABLE IF EXISTS "alembic_version_{name}" CASCADE'))
            conn.commit()
        engine.dispose()
        # The tree goes with tmp_path; ``app.modules.__path__`` is restored by
        # monkeypatch, and the imported package is left in sys.modules under a
        # uuid name nothing else can reach.


def _store_a_claim(table: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                f'INSERT INTO "{table}" (id, organization_id, note) '
                'VALUES (:id, :org, :note)'
            ),
            {'id': uuid.uuid4(), 'org': org_id, 'note': 'written under v0.1'},
        )
        conn.commit()
    engine.dispose()
    return org_id


class TestUpgradeKeepsTheData:
    def test_the_rows_written_under_the_old_version_are_still_there(
        self, fixture_module, tmp_path: Path
    ):
        name, table, root, modules_root = fixture_module
        org_id = _store_a_claim(table)

        v2 = _write_package(root, name, table, '0.2.0', with_status=True)
        upgrade_module(str(v2), allow_unsigned=True)

        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            rows = conn.execute(
                text(f'SELECT organization_id, note, status FROM "{table}"')
            ).all()
        engine.dispose()

        assert len(rows) == 1
        assert rows[0][0] == org_id
        assert rows[0][1] == 'written under v0.1'
        # The column v0.2's migration added, on the row v0.1 wrote.
        assert rows[0][2] == 'open'

    def test_the_new_migration_ran(self, fixture_module, tmp_path: Path):
        name, table, root, modules_root = fixture_module
        _store_a_claim(table)

        upgrade_module(
            str(_write_package(root, name, table, '0.2.0', with_status=True)),
            allow_unsigned=True,
        )

        engine = create_engine(settings.DATABASE_URL)
        columns = {c['name'] for c in inspect(engine).get_columns(table)}
        with engine.connect() as conn:
            revision = conn.execute(
                text(f'SELECT version_num FROM "alembic_version_{name}"')
            ).scalar()
        engine.dispose()

        assert 'status' in columns
        assert revision == '002_status'

    def test_a_file_the_new_version_dropped_is_gone(self, fixture_module):
        name, table, root, modules_root = fixture_module
        assert (modules_root / name / 'legacy.py').exists()

        upgrade_module(
            str(_write_package(root, name, table, '0.2.0', with_status=True)),
            allow_unsigned=True,
        )

        # A stale module left behind still imports, still registers and
        # still runs; copying over the old tree would have kept it.
        assert not (modules_root / name / 'legacy.py').exists()

    def test_the_tracking_entry_remembers_where_it_came_from(self, fixture_module):
        name, table, root, modules_root = fixture_module

        upgrade_module(
            str(_write_package(root, name, table, '0.2.0', with_status=True)),
            allow_unsigned=True,
        )

        entry = _module_meta._load_tracking()[name]
        assert entry['version'] == '0.2.0'
        assert entry['previous_version'] == '0.1.0'
        assert entry['upgraded_at']


class TestUpgradeRefusesWhatIsNotAnUpgrade:
    def test_the_same_version_needs_force(self, fixture_module):
        name, table, root, modules_root = fixture_module
        same = _write_package(root, name, table, '0.1.0', with_status=False)

        with pytest.raises(SystemExit) as exc:
            upgrade_module(str(same), allow_unsigned=True)

        assert exc.value.code == 1

    def test_an_unknown_module_is_not_upgraded_into_existence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'none.json')
        stranger = _write_package(
            tmp_path,
            f'absent_{uuid.uuid4().hex[:8]}',
            'absent_t',
            '1.0.0',
            with_status=False,
        )

        with pytest.raises(SystemExit) as exc:
            upgrade_module(str(stranger), allow_unsigned=True)

        assert exc.value.code == 1


class TestAnUpgradeThatFails:
    """The old module has to still be there afterwards.

    The upgrade moves the installed tree aside before the new one lands —
    that is what keeps a file the new version dropped from surviving — so
    a failure between the two leaves the installation with nothing at all
    unless the move is undone. The AST validator is the realistic way to
    fail there: it runs on the copied files, after the old ones are gone.
    """

    def test_the_previous_version_is_put_back(self, fixture_module):
        name, table, root, modules_root = fixture_module
        bad = _write_package(root, name, table, '0.2.0', with_status=True)
        # Refused outright by the safety scan, whatever the manifest says.
        (bad / 'backend' / 'router.py').write_text(
            'import subprocess\n\nfrom fastapi import APIRouter\n\n'
            'router = APIRouter()\n',
            encoding='utf-8',
        )

        with pytest.raises(SystemExit):
            upgrade_module(str(bad), allow_unsigned=True)

        installed = modules_root / name
        assert (installed / 'module.py').exists()
        assert (installed / 'legacy.py').exists(), 'v0.1 tree was not restored'
        assert '002_status.py' not in {
            f.name for f in (installed / 'migrations' / 'versions').iterdir()
        }
        assert _module_meta._load_tracking()[name]['version'] == '0.1.0'

    def test_the_data_is_untouched_either_way(self, fixture_module):
        name, table, root, modules_root = fixture_module
        org_id = _store_a_claim(table)
        bad = _write_package(root, name, table, '0.2.0', with_status=True)
        (bad / 'backend' / 'router.py').write_text(
            'import subprocess\n\nfrom fastapi import APIRouter\n\n'
            'router = APIRouter()\n',
            encoding='utf-8',
        )

        with pytest.raises(SystemExit):
            upgrade_module(str(bad), allow_unsigned=True)

        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            rows = (
                conn.execute(text(f'SELECT organization_id FROM "{table}"'))
                .scalars()
                .all()
            )
        engine.dispose()
        assert rows == [org_id]


class TestTheSharedTreeStaysOutOfIt:
    def test_the_install_lands_only_in_the_private_tree(self, fixture_module):
        """Every worker reads ``app/modules``; nothing here may appear in it.

        The migration doctor enumerates that tree, so a fixture installed
        there is a module the other worker meets mid-run — once as a module
        missing from its database, once as a directory that disappears under
        its feet. Both were observed on the same day, in opposite directions
        of the install→cleanup window.
        """
        name, _, _, modules_root = fixture_module

        assert (modules_root / name / 'module.py').is_file()
        assert not (SHARED_MODULES_ROOT / name).exists()
