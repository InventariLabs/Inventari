"""Community module package scaffolding — generates a starter package.

Extracted from module_packaging.py to keep file sizes manageable.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from rich.console import Console

from app.i18n import SUPPORTED_LANGUAGES

from ._module_meta import _VALID_NAME_RE, _reserved_name_refusal

console = Console()

# The repository's own address, spelled once: every link the scaffold writes
# into a generated package must name the same organisation the remote does.
# It drifted once — the README shipped a wrong organisation name while the
# remote, the clone URL in the deploy docs and twenty markdown files all said
# InventariLabs — and the false one was the address handed to authors.
GITHUB_REPO_URL = 'https://github.com/InventariLabs/Inventari'

# ---------------------------------------------------------------------------
# Scaffold community module package
# ---------------------------------------------------------------------------

# English is the one catalog a module must ship: every other language falls
# back to it key by key. The scaffold writes English alone and adds the others
# when the author asks for them. `{title}` is the module's display name.
_FRONTEND_CATALOGS = {
    'en': '{title} module.',
    'pl': 'Moduł {title}.',
    'de': 'Modul {title}.',
    'fr': 'Module {title}.',
    'es': 'Módulo {title}.',
    'pt': 'Módulo {title}.',
}

# Keys sit at the top level of the file: that is where get_module_error_message
# reads them, and a message nested under "errors" falls through to Core.
_BACKEND_CATALOGS = {
    'en': {'item_not_found': 'Item not found'},
    'pl': {'item_not_found': 'Nie znaleziono pozycji'},
    'de': {'item_not_found': 'Eintrag nicht gefunden'},
    'fr': {'item_not_found': 'Élément introuvable'},
    'es': {'item_not_found': 'Elemento no encontrado'},
    'pt': {'item_not_found': 'Item não encontrado'},
}

_MODULE_PY_TEMPLATE = """from app.core.module_sdk import define_module

from .router import router

# Metadata (name, version, display_name, icon, ...) is read from manifest.json —
# single source of truth, so there is nothing to keep in sync here.
# `app.core.module_sdk` is the one door into Core: everything this package
# imports that does not belong to the package itself comes from there (or from
# `app.core.contracts` for the DTOs and the model base), and the install-time
# safety scan refuses any other `app.` path.
# See app/modules/example_widgets for a fuller reference module.
module = define_module(router=router)
"""

_ROUTER_PY_TEMPLATE = """from fastapi import APIRouter, Depends

from app.core.module_sdk import (
    AppException,
    get_module_error_message,
    require_module,
)

router = APIRouter(dependencies=[Depends(require_module("{name}"))])


@router.get("/hello")
async def hello():
    return {{"message": "Hello from {name} module!"}}


@router.get("/items/{{item_id}}")
async def get_item(item_id: str):
    # A placeholder lookup that finds nothing, to show how a module raises a
    # translated error: the message comes from this module's own
    # backend/i18n/<lang>.json, keyed at the top level of the file. Replace it
    # with a real lookup.
    raise AppException(
        status_code=404,
        code="ITEM_NOT_FOUND",
        message=get_module_error_message("{name}", "item_not_found"),
    )
"""

_MODULE_TS_TEMPLATE = """import {{ lazy }} from 'react';
import {{ Package }} from 'lucide-react';
import {{ moduleRegistry }} from '@/module-sdk';

const IndexPage = lazy(() => import('./pages/IndexPage'));

// Translations need no registration: `i18n/config.ts` picks up
// `modules/<name>/i18n/*.json` as the module's namespace.
moduleRegistry.register({{
  name: '{name}',
  routes: [
    {{
      path: '{route}',
      component: IndexPage,
    }},
  ],
  // Without a launcher entry an enabled module has no tile on the home screen
  // and no way in but its address.
  launcher: {{
    displayName: '{name}:navigation.title',
    description: '{name}:launcher.description',
    icon: Package,
    color: 'bg-blue-500',
    category: 'business',
    order: 100,
  }},
  moduleNav: {{
    basePath: '{route}',
    items: [
      {{
        path: '',
        icon: Package,
        labelKey: '{name}:navigation.title',
      }},
    ],
  }},
}});
"""

# The shell renders a module page's title (FRONTEND_MODULE_GUIDE): the page
# hands it over through useModulePageHeader instead of drawing a heading of
# its own, so the screen opens on its h1.
_INDEX_PAGE_TSX_TEMPLATE = """import {{ useEffect }} from 'react';
import {{ useTranslation }} from 'react-i18next';
import {{ useModulePageHeader }} from '@/module-sdk';

export default function IndexPage() {{
  const {{ t }} = useTranslation('{name}');
  const {{ setHeader }} = useModulePageHeader();

  useEffect(() => {{
    setHeader({{ title: t('title'), subtitle: t('description') }});
  }}, [t, setHeader]);

  return <div className="space-y-6" />;
}}
"""

_MODELS_PY_TEMPLATE = '''"""Your module's own tables.

Tables declared here are the module's: the module's own migrations
(``migrations/versions/``) create them, never the platform's, and the
platform's autogenerate never proposes them.

The base is ``ModuleModelBase``, exported by the contract surface. It is not
``app.database.Base``: that is the core's base, its metadata is the core's,
and the install-time safety scan refuses the import to a module outside the
repository.

Every row belongs to an organization: keep ``organization_id`` and filter
every query by it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.contracts import ModuleModelBase


class Record(ModuleModelBase):
    """One row this module keeps — rename it to what your module stores."""

    __tablename__ = '{name}_records'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # No ForeignKey here: this base's metadata holds the module's tables only,
    # so an ORM-level ForeignKey to the core's organizations table cannot
    # resolve its target and the first flush fails. The migration
    # (migrations/versions/001_initial.py) declares the constraint instead; the
    # database enforces it and the core's metadata stays out of the module.
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
'''

_MIGRATIONS_ENV_PY_TEMPLATE = '''"""Alembic environment for this module's own migration chain.

The chain is recorded in ``alembic_version_{name}``, apart from the platform's
``alembic_version``: ``manage.py db upgrade-modules`` applies this one, and
neither waits for the other.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default switches off every logger
    # created before this call, and the platform's loggers are older than it.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from app.core.contracts import ModuleModelBase

# Registers the module's models — and their tables — on the metadata below.
from app.modules.{name}.models import *  # noqa: F401,F403

target_metadata = ModuleModelBase.metadata
VERSION_TABLE = 'alembic_version_{name}'


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={{'paramstyle': 'named'}},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


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


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

_MIGRATION_001_TEMPLATE = '''"""Create this module's first table.

The scaffold's starting point: the table the model in ``models.py`` declares.
A later change to that file gets a revision beside this one (``002_...``)
whose ``down_revision`` names this revision. ``manage.py db upgrade-modules``
applies the chain at startup, the first time on the startup after the install;
enabling the module for an organization runs no migration.

The table and index are created through ``create_table_if_absent`` /
``create_index_if_absent``: an installation that already holds them (a restore,
or a core revision that created them earlier) replays this revision without
failing. Both come from ``app.core.module_sdk``, the only door this module's
code may import Core through.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.core.module_sdk import create_index_if_absent, create_table_if_absent

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('{name}',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        '{name}_records',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_{name}_records_organization_id',
        '{name}_records',
        ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_{name}_records_organization_id', table_name='{name}_records')
    op.drop_table('{name}_records')
'''


_TEST_RECORDS_PY_TEMPLATE = '''"""The module's table exists in the test database and keeps a row.

Run it, and everything else under ``backend/tests/``, with the loop in the
platform's ``docs/MODULE_TESTING_GUIDE.md`` (*Running a community package's
tests*). ``db_session`` and ``test_household`` come from the platform's own
conftest; the worker's test database already holds this module's tables,
built from the metadata ``models.py`` declares.
"""

from app.modules.{name}.models import Record


def test_a_record_is_kept_for_its_organization(db_session, test_household):
    db_session.add(Record(organization_id=test_household.id))
    db_session.commit()

    kept = db_session.query(Record).filter_by(organization_id=test_household.id).all()

    assert len(kept) == 1
'''


def scaffold_community_module(  # noqa: PLR0915 - existing complexity/size
    module_name: str, *, output_dir: str = '.', languages: Iterable[str] = ()
) -> None:
    """Generate a standalone community module package in *output_dir*/<module_name>/.

    Only the English catalogs are written unless *languages* names more of the
    languages the core ships.
    """
    unknown = sorted(set(languages) - set(SUPPORTED_LANGUAGES))
    if unknown:
        console.print(
            f'[red]✗ Unknown language {", ".join(unknown)}. '
            f'The core ships: {", ".join(SUPPORTED_LANGUAGES)}.[/]'
        )
        raise SystemExit(1)
    catalog_languages = {'en', *languages}

    if not _VALID_NAME_RE.match(module_name):
        console.print(
            f'[red]✗ Invalid module name {module_name!r}. '
            f'Use lowercase letters, digits and underscores only.[/]'
        )
        raise SystemExit(1)
    refusal = _reserved_name_refusal(module_name)
    if refusal is not None:
        console.print(f'[red]✗ {refusal}[/]')
        raise SystemExit(1)

    out = Path(output_dir).expanduser().resolve() / module_name
    if out.exists():
        console.print(f'[red]✗ Directory already exists: {out}[/]')
        raise SystemExit(1)

    human = module_name.replace('_', ' ').title()
    route = '/' + module_name.replace('_', '-')

    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        console.print(f'  created  {path.relative_to(out.parent)}')

    def touch(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    console.print(
        f'\n[blue]Scaffolding community module package [bold]{module_name}[/bold]...[/]\n'
    )

    # module.yaml
    # inventari_min_version tracks the CURRENT platform version — a
    # freshly scaffolded module must install on the platform that built it.
    from app.core.version import get_platform_version

    # 0.1.0, not 1.0.0: docs/MODULE_VERSIONING.md heads a section with "no
    # 1.0.0 while the platform is on 0.x" and then declines to police it. A
    # tool that hands every author the one number its own document argues
    # against makes the argument for nothing.
    write(
        out / 'module.yaml',
        f'name: {module_name}\n'
        f'version: "0.1.0"\n'
        f'inventari_min_version: "{get_platform_version()}"\n'
        f'author: "Your Name"\n'
        f'description: "Add your description here."\n'
        f'license: "AGPL-3.0"\n'
        f'homepage: "https://github.com/yourname/inventari-module-{module_name.replace("_", "-")}"\n'
        f'\nrequires: []\n'
        f'\ncomponents:\n'
        f'  backend: true\n'
        f'  frontend: true\n',
    )

    # backend/
    write(
        out / 'backend' / '__init__.py',
        'from .module import module  # noqa: F401\n',
    )
    # `capabilities` is the import allow-list checked by the AST safety scan
    # (database / filesystem / network / process). The generated model and its
    # migration import SQLAlchemy, so the package declares `database`; a module
    # that drops them drops the capability with them. An import of a
    # restricted library the manifest does not declare is refused on install,
    # so declare only what the module actually needs.
    manifest_content = (
        json.dumps(
            {
                'name': module_name,
                'version': '0.1.0',
                'inventari_min_version': get_platform_version(),
                'display_name': human,
                'module_type': 'community',
                'capabilities': ['database'],
            },
            indent=2,
        )
        + '\n'
    )
    write(out / 'backend' / 'manifest.json', manifest_content)
    write(
        out / 'backend' / 'module.py',
        _MODULE_PY_TEMPLATE,
    )
    write(out / 'backend' / 'router.py', _ROUTER_PY_TEMPLATE.format(name=module_name))
    write(
        out / 'backend' / 'models.py',
        _MODELS_PY_TEMPLATE.format(name=module_name),
    )
    write(
        out / 'backend' / 'migrations' / 'env.py',
        _MIGRATIONS_ENV_PY_TEMPLATE.format(name=module_name),
    )
    write(
        out / 'backend' / 'migrations' / 'versions' / '001_initial.py',
        _MIGRATION_001_TEMPLATE.format(name=module_name),
    )
    write(out / 'backend' / 'schemas.py', '# Pydantic schemas for this module\n')
    write(out / 'backend' / 'services.py', '# Business logic for this module\n')
    for lang, messages in _BACKEND_CATALOGS.items():
        if lang not in catalog_languages:
            continue
        write(
            out / 'backend' / 'i18n' / f'{lang}.json',
            json.dumps(messages, indent=2, ensure_ascii=False) + '\n',
        )
    # Tests live in the author's tree only: the installer drops backend/tests/
    # before copying, so this directory never reaches an installed module.
    touch(out / 'backend' / 'tests' / '__init__.py')
    write(
        out / 'backend' / 'tests' / 'test_records.py',
        _TEST_RECORDS_PY_TEMPLATE.format(name=module_name),
    )

    # frontend/
    write(
        out / 'frontend' / 'module.ts',
        _MODULE_TS_TEMPLATE.format(name=module_name, route=route),
    )
    write(
        out / 'frontend' / 'pages' / 'IndexPage.tsx',
        _INDEX_PAGE_TSX_TEMPLATE.format(name=module_name),
    )
    for lang, description in _FRONTEND_CATALOGS.items():
        if lang not in catalog_languages:
            continue
        write(
            out / 'frontend' / 'i18n' / f'{lang}.json',
            json.dumps(
                {
                    'title': human,
                    'description': description.format(title=human),
                    'navigation': {'title': human},
                    'launcher': {'description': description.format(title=human)},
                },
                indent=2,
                ensure_ascii=False,
            )
            + '\n',
        )
    write(
        out / 'frontend' / 'types' / 'index.ts',
        f'// Types for the {module_name} module\n',
    )
    touch(out / 'frontend' / 'components' / '.gitkeep')
    touch(out / 'frontend' / 'hooks' / '.gitkeep')

    # README
    write(
        out / 'README.md',
        f'# inventari-module-{module_name.replace("_", "-")}\n\n'
        f'{human} module for [Inventari]({GITHUB_REPO_URL}).\n\n'
        f'## Installation\n\n'
        f'```bash\npython manage.py module install https://github.com/yourname/inventari-module-{module_name.replace("_", "-")}.git --rev v0.1.0\n```\n\n'
        f'## Development\n\n'
        f'See [MODULES_GUIDE.md]({GITHUB_REPO_URL}/blob/main/MODULES_GUIDE.md).\n',
    )

    console.print(f'\n[green]✓ Package created at {out}/[/]')
    console.print('')
    console.print('[yellow]Next steps:[/]')
    console.print(
        f'  1. Edit [cyan]{module_name}/module.yaml[/] (author, description, homepage)'
    )
    console.print(f'  2. Implement [cyan]{module_name}/backend/router.py[/]')
    console.print(f'  3. Implement [cyan]{module_name}/frontend/pages/IndexPage.tsx[/]')
    # The path, not a name relative to a working directory the reader may not
    # be standing in: with --output the two differ, and the Makefile always
    # passes one. The key likewise: the command runs in the backend
    # container, whose working directory is /app, and the quickstart writes
    # the key to /modules-workspace.
    console.print(
        f'  4. Sign the package:  [bold]python manage.py module sign {out} --key /modules-workspace/my-ed25519.key --key-id my-releases[/]'
    )
    console.print(
        f'  5. Test locally:  [bold]python manage.py module install {out}[/]'
        ' (with your key in MODULE_SIGNING_PUBLIC_KEYS, or --allow-unsigned)'
    )
    console.print(
        '  6. Push to GitHub, tag a release (git tag v0.1.0 && git push origin v0.1.0) and share — '
        'installs from git must pin a --rev'
    )
