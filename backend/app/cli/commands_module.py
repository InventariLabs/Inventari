from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from app.core.logging import get_logger
from app.core.module_safety import REPO_SHIPPED_MODULES
from app.i18n import MAINTAINED_LANGUAGES, SUPPORTED_LANGUAGES

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.module_tracking import ModuleTrackingEntry

module_app = typer.Typer(no_args_is_help=True)
console = Console()
logger = get_logger(__name__)

# `en` is validated separately and always required; the other maintained
# languages follow the module type (see module_validator.is_strict_i18n). A
# community language is never checked: it falls back to English per key.
_OPTIONAL_I18N = tuple(lang for lang in MAINTAINED_LANGUAGES if lang != 'en')


@module_app.command()
def install(
    source: str = typer.Argument(
        ...,
        help='Local path or git URL (https://...git / git@...) to the module package.',
    ),
    rev: str = typer.Option(
        None,
        '--rev',
        help='Tag or commit to install. Required for git sources.',
    ),
    signature: str = typer.Option(
        None,
        '--signature',
        help='Path to a module.sig file. Defaults to module.sig in the package root.',
    ),
    allow_unsigned: bool = typer.Option(
        False,
        '--allow-unsigned',
        help='Install a package with no signature, accepting the risk explicitly.',
    ),
):
    """Install a community module from a local directory or git repository.

    The module package must contain a module.yaml file and backend/ and/or
    frontend/ subdirectories following the Inventari community module layout.

    Git sources must be pinned with --rev, so that the installed code is a
    decision rather than a matter of timing. A signed package is verified
    against the keys in MODULE_SIGNING_PUBLIC_KEYS; an unsigned package
    installs only with --allow-unsigned.

    Example:
        python manage.py module install ./inventari-module-warranty-tracker
        python manage.py module install https://github.com/user/mod.git --rev v1.2.0
    """
    from app.cli.module_packaging import install_module

    typer.echo(
        'Note: module code runs in-process with full access to the database '
        'and the filesystem.\n'
        "The AST validator scans the module's Python files (its own tests "
        'aside) — including\n'
        'models.py and migrations/, which execute on import and on install — '
        'but it is not a\n'
        'security sandbox: it matches imports by literal name.\n'
        'Install modules you trust, and read the diff when you bump a revision.'
    )
    try:
        install_module(
            source,
            rev,
            signature_file=Path(signature).expanduser() if signature else None,
            allow_unsigned=allow_unsigned,
        )
    except ValueError as exc:
        # A refusal the installer predicted (missing --rev, unreachable
        # source, unknown revision) is one sentence for the user, not a
        # stack for a developer. The traceback stays for the unexpected.
        console.print(f'[red]✗ {exc}[/]')
        raise typer.Exit(1) from exc


@module_app.command()
def uninstall(
    module_name: str = typer.Argument(
        ..., help='Name of the community module to remove.'
    ),
    force: bool = typer.Option(
        False,
        '--force',
        '-f',
        help='Skip confirmation prompts — including the type-"data" gate that '
        '--drop-data requires to drop every table the module owns.',
    ),
    drop_data: bool = typer.Option(
        False,
        '--drop-data',
        help="DROP the module's tables with every organization's data in them.",
    ),
):
    """Uninstall a previously installed community module.

    Removes the module files from backend/app/modules/ and frontend/src/modules/,
    updates the community_modules.json tracking file, and clears the module's
    installation record so a later reinstall runs its on_install hook again.

    The module's data is kept. What it leaves behind — its own tables, the
    organizations that still list it, audit entries, webhook subscriptions,
    stored files — is counted and printed before anything is removed.
    --drop-data runs the module's on_uninstall hook instead, whose default
    implementation drops the module's tables for every organization on this
    installation; it is confirmed separately, by typing the word "data".

    Core (built-in) modules cannot be uninstalled via this command.
    """
    from app.cli.module_packaging import uninstall_module

    uninstall_module(module_name, force=force, drop_data=drop_data)


@module_app.command()
def upgrade(
    source: str = typer.Argument(
        ...,
        help='Local path or git URL (https://...git / git@...) to the new package.',
    ),
    rev: str = typer.Option(
        None,
        '--rev',
        help='Tag or commit to install. Required for git sources.',
    ),
    signature: str = typer.Option(
        None,
        '--signature',
        help='Path to a module.sig file. Defaults to module.sig in the package root.',
    ),
    allow_unsigned: bool = typer.Option(
        False,
        '--allow-unsigned',
        help='Upgrade to a package with no signature, accepting the risk explicitly.',
    ),
    force: bool = typer.Option(
        False,
        '--force',
        '-f',
        help='Install the package even when it is not newer than what is installed.',
    ),
):
    """Upgrade an installed community module to a newer package.

    Replaces the module's files, runs its migrations and leaves the data
    alone — the tables the module owns keep every row. This is the route
    from one version to the next: uninstalling first would have taken the
    data with it.

    The on_upgrade hook runs on the next backend restart, from the new
    version's own code, with the previously installed version as
    old_version.

    Example:
        python manage.py module upgrade ./inventari-module-warranty-tracker
        python manage.py module upgrade https://github.com/user/mod.git --rev v0.2.0
    """
    from app.cli._module_upgrade import upgrade_module

    try:
        upgrade_module(
            source,
            rev,
            signature_file=Path(signature).expanduser() if signature else None,
            allow_unsigned=allow_unsigned,
            force=force,
        )
    except ValueError as exc:
        console.print(f'[red]✗ {exc}[/]')
        raise typer.Exit(1) from exc


@module_app.command('sign')
def sign(
    source: str = typer.Argument(
        ..., help='Path to the module package directory (with module.yaml).'
    ),
    key: str = typer.Option(
        ...,
        '--key',
        help='Path to the file holding the base64 raw Ed25519 private key.',
    ),
    key_id: str = typer.Option(
        ...,
        '--key-id',
        help='Identifier for this key as it will appear to installers '
        '(they trust keys by id).',
    ),
):
    """Sign a community module package so installers can verify it.

    Writes module.sig next to module.yaml, binding an Ed25519 signature of
    the package digest (plus the module's name and version) to your key.
    Installers verify it against the keys listed in their
    MODULE_SIGNING_PUBLIC_KEYS. Re-run the command after every content
    change — a signature covers the exact bytes signed.

    Example:
        python manage.py module sign ./inventari-module-warranty-tracker \
            --key my-ed25519.key --key-id acme-releases
    """
    from pathlib import Path as _Path

    from ._module_signing import sign_module

    source_dir = _Path(source)
    meta_file = source_dir / 'module.yaml'
    if not meta_file.exists():
        console.print(f'[red]✗ {meta_file} not found — not a module package.[/]')
        raise typer.Exit(code=1)
    import yaml as _yaml  # type: ignore[import-untyped]

    meta = _yaml.safe_load(meta_file.read_text(encoding='utf-8'))
    try:
        sig_path = sign_module(source_dir, meta, _Path(key), key_id)
    except FileNotFoundError as exc:
        console.print(f'[red]✗ {exc}[/]')
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f'[red]✗ Cannot sign the package: {exc}[/]')
        raise typer.Exit(code=1) from exc
    console.print(
        f'[green]✓ Signed {source_dir.name} (key {key_id}) → {sig_path.name}.[/]'
    )
    console.print(
        'Ship the package with module.sig inside. Installers trust your key '
        'by listing it in their MODULE_SIGNING_PUBLIC_KEYS as '
        f'{key_id}=<base64 public key>.'
    )


@module_app.command('new-community')
def new_community(
    module_name: str = typer.Argument(
        ..., help='Name for the community module package.'
    ),
    output_dir: str = typer.Option(
        '.',
        '--output',
        '-o',
        help='Directory where the package folder will be created.',
    ),
    language: list[str] = typer.Option(
        [],
        '--language',
        '-l',
        help=(
            'A language besides English to write a catalog for ('
            + ', '.join(lang for lang in SUPPORTED_LANGUAGES if lang != 'en')
            + '); repeat for several. English is always written and is the '
            'only one a module has to ship.'
        ),
    ),
):
    """Scaffold a standalone community module package ready for distribution.

    Generates a self-contained directory with the unified layout:

        <module_name>/
          module.yaml        — top-level community manifest
          backend/           — FastAPI module (identical to in-tree module structure)
          frontend/          — React module (identical to in-tree module structure)

    Translation catalogs are written for English only; add `-l pl -l de` for
    more of the languages the core ships.
    """
    from app.cli.module_packaging import scaffold_community_module

    scaffold_community_module(module_name, output_dir=output_dir, languages=language)


@module_app.command()
def create(module_name: str = typer.Argument(..., help='Name of the new module')):
    """Generate boilerplate structure for a new module."""
    from app.cli.module_generator import create_module

    create_module(module_name)


def _validate_module_dir(
    module_dir: Path,
    *,
    allow_core: bool,
    errors: list[str],
    warnings: list[str],
) -> bool:
    """Run every check on one module directory; ``True`` when none failed."""
    from app.cli._module_meta import _reserved_name_refusal
    from app.cli.module_validator import (
        skipped_paths,
        validate_deprecated_core_api,
        validate_i18n,
        validate_manifest,
        validate_manifest_icon,
        validate_permission_actions,
        validate_safety,
    )
    from app.core._registry_class import REPO_MODULES_ROOT
    from app.core.module_manifest_schema import ModuleManifest

    errors_before = len(errors)

    declared_caps: list[str] = []
    try:
        manifest = ModuleManifest.load(module_dir)
        declared_caps = [str(c) for c in manifest.capabilities]
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            'manifest.json unreadable for %s; declared_caps left empty',
            module_dir,
            exc_info=exc,
        )

    # As at discovery, a directory is the repository's own only when it IS
    # the repository's path, never a same-named directory somewhere else.
    repo_dir = REPO_MODULES_ROOT / module_dir.name
    own = repo_dir.exists() and repo_dir.resolve() == module_dir.resolve()
    # --allow-core spares the scan to the modules this repository ships and
    # nothing else: a switch that skips it for whatever directory is named
    # turns the gate an author runs before install into a pass for anything.
    skip_scan = allow_core and own and module_dir.name in REPO_SHIPPED_MODULES
    if allow_core and not skip_scan:
        warnings.append(
            f'{module_dir.name}: --allow-core covers only the modules this '
            f'repository ships; the safety scan ran'
        )

    errors.extend(validate_manifest(module_dir))
    if not skip_scan:
        errors.extend(validate_safety(module_dir, declared_caps))

    # The installer refuses a name the core answers to; saying so here
    # spares the author a module written around it. As at discovery, the
    # repository's own directories keep their names.
    if not own:
        refusal = _reserved_name_refusal(module_dir.name)
        if refusal is not None:
            errors.append(refusal)

    # i18n completeness. `validate_i18n` decides from module_type: missing
    # pl/de/fr/es is an error for core/official and no finding at all for
    # community, so a community module shipping only en.json passes clean.
    for severity, message in validate_i18n(module_dir):
        (errors if severity == 'error' else warnings).append(message)

    # A symlink ends the scan's walk where it points outside the tree, and a
    # dangling one points nowhere at all, so "clean" would be a report over a
    # tree nobody read. Each unread shape is named for what it is instead;
    # links resolved inside the tree are content the walk already read and
    # are not reported.
    for skipped in skipped_paths(module_dir):
        warnings.append(f'{module_dir.name}: not read (symlink): {skipped}')

    # Usage of a method the register retires is a migration debt with a
    # deadline, not a refusal: the module works until the removal, and the
    # report is what tells the author to move (warnings only).
    warnings.extend(validate_deprecated_core_api(module_dir))
    warnings.extend(validate_manifest_icon(module_dir))
    warnings.extend(validate_permission_actions(module_dir))

    return len(errors) == errors_before


def _laid_out(
    found: list[Path], staging: Path, errors: list[str], warnings: list[str]
) -> list[Path]:
    """The directories to check: an installed backend as it is, and a
    package as ``module install`` would land its backend."""
    from app.cli.module_packaging import stage_package_backend

    dirs: list[Path] = []
    for directory in sorted(found):
        if not (directory / 'module.yaml').exists():
            dirs.append(directory)
            continue
        try:
            staged = stage_package_backend(directory, staging)
        except ValueError as exc:  # OperatorError: what the installer refuses too
            errors.append(f'{directory.name}: {exc}')
            continue
        if staged is None:
            warnings.append(
                f'{directory.name}: the package declares no backend, so there is '
                f'nothing for module discovery to load'
            )
            continue
        dirs.append(staged)
    return dirs


@module_app.command()
def validate(
    module: str | None = typer.Option(
        None,
        help=(
            'Validate only a single module by directory name: an installed '
            'backend, or a package (module.yaml with backend/ beside it)'
        ),
    ),
    base_path: str = typer.Option('app/modules', help='Path to modules directory'),
    allow_core: bool = typer.Option(
        False,
        '--allow-core',
        help='Skip the safety scan for the modules this repository ships',
    ),
):
    """Validate module manifest and import safety rules."""
    import tempfile

    from app.cli.module_validator import get_module_dirs, validate_importable

    path = Path(base_path)
    if not path.exists():
        console.print(f'[red]Modules path does not exist: {path}[/]')
        raise typer.Exit(code=1)

    found = get_module_dirs(path, module)
    if module and not found:
        console.print(f'[red]Module not found: {module}[/]')
        raise typer.Exit(code=1)

    all_errors: list[str] = []
    all_warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix='inventari_validate_') as staging:
        admitted: list[Path] = []
        for module_dir in _laid_out(found, Path(staging), all_errors, all_warnings):
            if _validate_module_dir(
                module_dir,
                allow_core=allow_core,
                errors=all_errors,
                warnings=all_warnings,
            ):
                admitted.append(module_dir)

        # Last, and once for every module the checks above admitted: it
        # starts an interpreter, and it is the only check that sees a package
        # discovery will reject on import. Importing runs the package, so a
        # module refused above — by the safety scan above all — is never
        # imported here.
        all_errors.extend(validate_importable(admitted))

    for warning in all_warnings:
        console.print(f'[yellow]![/] {warning}')

    if all_errors:
        console.print('[red]Module validation failed:[/]')
        for error in all_errors:
            console.print(f'  - {error}')
        raise typer.Exit(code=1)

    console.print('[green]✔ Module validation passed.[/]')


def _signature_display(entry: ModuleTrackingEntry) -> str:
    status = str(entry.get('signature_status', ''))
    if status == 'verified':
        return '[green]verified[/]'
    if status == 'unsigned':
        return '[yellow]unsigned[/]'
    return ''


def _version_display(version: str | None, entry: ModuleTrackingEntry | None) -> str:
    """The installed version, and what it replaced if it replaced something.

    An installation that was upgraded and one installed fresh at the same
    version hold different data — the first has rows from before the bump —
    and the table showed them identically. ``module upgrade`` records what
    it came from; this is where somebody reads it.
    """
    shown = version or ''
    previous = (entry or {}).get('previous_version')
    return f'{shown} (was {previous})' if previous else shown


def _displayed_module_type(name: str, module_type: str, tracked: bool) -> str:
    """Same discriminator as the store card: who stands behind a module is
    where its code comes from — a tracked module reads as community, and
    so does an untracked one whose name the repository does not ship
    (``REPO_SHIPPED_MODULES``); only a shipped name keeps its manifest
    claim."""
    if tracked or name not in REPO_SHIPPED_MODULES:
        return 'community'
    return module_type


def _print_rejected_modules() -> set[str]:
    """Name the modules discovery rejected, with the reason; return the names.

    A rejected module is not waiting for a restart — the restart is what
    rejected it — so it is named here, not under "not yet active".
    """
    from app.core.module_registry import module_registry

    rejected = sorted(
        module_registry.get_rejected_modules(), key=lambda r: r.module_name
    )
    if rejected:
        console.print('')
        console.print('[red]These modules are rejected and do not load:[/]')
    for record in rejected:
        console.print(
            f'  - [cyan]{record.module_name}[/]: {escape(record.reason)}',
            soft_wrap=True,
        )
    return {record.module_name for record in rejected}


@module_app.command('list')
def list_modules(json_output: bool = typer.Option(False, '--json')):
    """Display all registered modules and their status."""
    from app.cli import bootstrap_db

    bootstrap_db()
    from app.cli.module_packaging import TrackingEntry, list_community_modules
    from app.core.module_registry import module_registry

    modules = module_registry.get_all()
    community: dict[str, TrackingEntry] = dict(list_community_modules())

    if json_output:
        export = []
        for mod in sorted(modules, key=lambda m: m.metadata.name):
            meta = mod.metadata
            mod_type = _displayed_module_type(
                meta.name, meta.module_type, meta.name in community
            )
            entry: dict[str, object] = {
                'name': meta.name,
                'version': meta.version,
                'display_name': meta.display_name,
                'module_type': mod_type,
            }
            if meta.name in community:
                entry['source'] = community[meta.name].get('source', '')
                entry['signature_status'] = community[meta.name].get(
                    'signature_status', ''
                )
                entry['signature_key_id'] = community[meta.name].get(
                    'signature_key_id', ''
                )
                entry['signature_verified_at'] = community[meta.name].get(
                    'signature_verified_at'
                )
                entry['previous_version'] = community[meta.name].get(
                    'previous_version', ''
                )
                entry['upgraded_at'] = community[meta.name].get('upgraded_at')
            export.append(entry)
        typer.echo(json.dumps(export, indent=2))
        return

    if not modules:
        console.print('[yellow]No modules registered.[/]')
        _print_rejected_modules()
        return

    table = Table(title='Registered Modules')
    table.add_column('Name', style='cyan')
    table.add_column('Version', style='green')
    table.add_column('Display Name')
    table.add_column('Type', style='yellow')
    table.add_column('Source')
    table.add_column('Signature')

    type_styles = {
        'core': 'bold blue',
        'official': 'green',
        'cloud': 'magenta',
        'community': 'yellow',
    }

    for mod in sorted(modules, key=lambda m: m.metadata.name):
        meta = mod.metadata
        tracked = meta.name in community
        mod_type = _displayed_module_type(meta.name, meta.module_type, tracked)
        source = community[meta.name].get('source', '') if tracked else ''
        signature = _signature_display(community[meta.name]) if tracked else ''
        style = type_styles.get(mod_type, '')
        type_display = f'[{style}]{mod_type}[/{style}]' if style else mod_type
        table.add_row(
            meta.name,
            _version_display(meta.version, community.get(meta.name)),
            meta.display_name,
            type_display,
            source,
            signature,
        )

    console.print(table)

    rejected_names = _print_rejected_modules()

    # Show community modules that are tracked but not yet loaded (e.g. after install, before restart)
    loaded_names = {m.metadata.name for m in modules}
    unloaded = [
        (n, e)
        for n, e in community.items()
        if n not in loaded_names and n not in rejected_names
    ]
    if unloaded:
        console.print('')
        console.print(
            '[yellow]The following community modules are installed but not yet active '
            '(restart backend to load):[/]'
        )
        for mod_name, unloaded_entry in unloaded:
            console.print(f'  - [cyan]{mod_name}[/] v{unloaded_entry["version"]}')


#: A ``routes: []`` declaration: the module draws no page of its own.
_NO_ROUTES = re.compile(r'routes:\s*\[\s*\]')
#: A launcher tile the home screen does not show.
_HIDDEN_TILE = re.compile(r'launcher:\s*\{[^}]*hidden:\s*true', re.DOTALL)


def _needs_module_nav(module_ts: str) -> bool:
    """A module with pages of its own, opened from a home-screen tile.

    One that lives in settings declares no routes, and one whose only page is
    a deep link (printing's label scan) hides its tile: neither has anything
    to navigate between.
    """
    has_pages = 'routes:' in module_ts and not _NO_ROUTES.search(module_ts)
    has_tile = 'launcher:' in module_ts and not _HIDDEN_TILE.search(module_ts)
    return has_pages and has_tile


def _reads_own_namespace(frontend_dir: Path, module_name: str) -> bool:
    """Whether the frontend half reads a key from the module's own namespace.

    A ``"<module>:key"``, ``useTranslation("<module>")`` (alone or first in a
    list) or ``ns: "<module>"``; the module's name in ``register`` is not one.
    """
    name = re.escape(module_name)
    reads = re.compile(
        rf'["\']{name}:|useTranslation\(\s*\[?\s*["\']{name}["\']|ns:\s*["\']{name}["\']'
    )
    return any(
        reads.search(path.read_text(encoding='utf-8'))
        for path in frontend_dir.rglob('*.ts*')
        if '.test.' not in path.name
    )


def _has_schemas(module_dir: Path) -> bool:
    """``schemas.py``, or schemas split into ``_schemas_*.py`` (maker)."""
    return (module_dir / 'schemas.py').exists() or any(module_dir.glob('_schemas_*.py'))


def _serves_routes(module_dir: Path) -> bool:
    """False for a module whose definition hands over an empty ``APIRouter()``."""
    module_py = module_dir / 'module.py'
    if not module_py.exists():
        return True
    return 'router=APIRouter()' not in module_py.read_text(encoding='utf-8')


def _smoke_frontend_half(
    frontend_dir: Path,
    module_dir: Path,
    module_name: str,
    check: Callable[[str, bool], None],
) -> None:
    """The frontend half of ``module smoke``: its file, catalogs and navigation."""
    from app.cli.module_validator import is_strict_i18n

    if not frontend_dir.exists():
        console.print('  [yellow]![/] frontend module dir (optional) not found')
        return
    check('frontend module.ts exists', (frontend_dir / 'module.ts').exists())
    # Same rule on the frontend side: en.json required, the rest only for a
    # core or official module - for a module that reads a namespace of its own.
    if not _reads_own_namespace(frontend_dir, module_name):
        console.print('  frontend i18n: none - it reads no namespace of its own')
    else:
        check('frontend i18n/en.json', (frontend_dir / 'i18n' / 'en.json').exists())
        # A community module owes English only: a line per language it did
        # not ship would read as a problem above "validation passed".
        if is_strict_i18n(module_dir):
            for lang in _OPTIONAL_I18N:
                if not (frontend_dir / 'i18n' / f'{lang}.json').exists():
                    check(f'frontend i18n/{lang}.json', False)

    module_ts_path = frontend_dir / 'module.ts'
    module_ts = (
        module_ts_path.read_text(encoding='utf-8') if module_ts_path.exists() else ''
    )
    if _needs_module_nav(module_ts):
        check('uses moduleNav', 'moduleNav' in module_ts)
    check('no deprecated navItems', 'navItems' not in module_ts)


@module_app.command()
def smoke(  # noqa: PLR0915 - existing complexity/size
    module_name: str = typer.Argument(..., help='Module to smoke-test'),
    base_path: str = typer.Option('app/modules', help='Path to modules directory'),
):
    """Run comprehensive smoke test on a single module."""
    from app.cli.module_validator import (
        validate_i18n,
        validate_manifest,
        validate_safety,
    )

    module_dir = Path(base_path) / module_name
    if not module_dir.is_dir():
        console.print(f'[red]Module directory not found: {module_dir}[/]')
        raise typer.Exit(code=1)

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = '') -> None:
        checks.append((name, passed, detail))
        icon = '[green]✓[/]' if passed else '[red]✗[/]'
        msg = f'  {icon} {name}'
        if detail:
            msg += f' — {detail}'
        console.print(msg)

    console.print(f'\n[bold]Smoke test: {module_name}[/]\n')

    from app.core.module_manifest_schema import ModuleManifest

    try:
        manifest = ModuleManifest.load(module_dir)
        check('manifest.json valid', True)
        check('manifest name matches directory', manifest.name == module_name)
        # An empty list is a valid declaration (the module imports nothing restricted);
        # which capabilities may be declared is the manifest's own validation.
        console.print(
            f'  capabilities: {[str(c) for c in manifest.capabilities] or "none"}'
        )
    except FileNotFoundError:
        check('manifest.json exists', False)
    except (OSError, TypeError, ValueError) as exc:
        check('manifest.json valid', False, str(exc))

    check('__init__.py exists', (module_dir / '__init__.py').exists())
    check('module.py exists', (module_dir / 'module.py').exists())
    if _serves_routes(module_dir):
        check('router.py exists', (module_dir / 'router.py').exists())
    else:
        console.print('  router: none - the module serves no HTTP route')
    check('schemas', _has_schemas(module_dir), 'schemas.py or _schemas_*.py')

    manifest_errors = validate_manifest(module_dir)
    check('manifest validation', not manifest_errors, '; '.join(manifest_errors))

    declared_caps: list[str] = []
    try:
        manifest = ModuleManifest.load(module_dir)
        declared_caps = [str(c) for c in manifest.capabilities]
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            'manifest.json unreadable for %s; declared_caps left empty',
            module_dir,
            exc_info=exc,
        )

    safety_errors = validate_safety(module_dir, declared_caps)
    check('AST safety', not safety_errors, '; '.join(safety_errors[:3]))

    # One source of truth for i18n completeness (module_validator.validate_i18n):
    # the flat five-language list this used to carry failed community modules for
    # missing pl/de/fr/es, which is only an error for core and official ones.
    i18n_findings = validate_i18n(module_dir)
    if not i18n_findings:
        check('i18n complete', True)
    for severity, message in i18n_findings:
        if severity == 'error':
            check('i18n', False, message)
        else:
            console.print(f'  [yellow]![/] {message}')

    from app.cli._module_meta import FRONTEND_MODULES_DIR

    _smoke_frontend_half(
        FRONTEND_MODULES_DIR / module_name, module_dir, module_name, check
    )

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    console.print('')
    if passed == total:
        console.print(f'[bold green]All {total} checks passed.[/]')
    else:
        console.print(f'[bold red]{passed}/{total} checks passed.[/]')
        raise typer.Exit(code=1)


@module_app.command()
def schema():
    """Export manifest.json JSON Schema to stdout (for IDE config or docs)."""
    from app.core.module_manifest_schema import ModuleManifest

    typer.echo(json.dumps(ModuleManifest.model_json_schema(), indent=2))
