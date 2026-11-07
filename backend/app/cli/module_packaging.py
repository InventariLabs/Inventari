"""
Community module packaging — install and uninstall logic.

Handles the full lifecycle of a community module package:
  - Parsing module.yaml (unified cross-layer manifest)
  - Copying backend/ and frontend/ trees into the correct in-tree locations
  - Running AST safety validation before finalizing the copy
  - Tracking state in backend/data/community_modules.json (deployment state,
    outside the tracked tree)
  - Reversible: rolls back copied files if validation fails
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from app.core.operator_error import OperatorError
from app.core.version import check_min_version

from ._module_meta import (
    _VALID_NAME_RE,
    BACKEND_MODULES_DIR,
    FRONTEND_MODULES_DIR,
    ModuleYaml,
    TrackingEntry,  # re-exported for backward compatibility
    _get_reserved_module_names,
    _load_tracking,
    _parse_module_yaml,
    _reserved_name_refusal,
    _run_ast_validation,
    _save_tracking,
    compose_command,
    deployment_steps,
    module_tree_permissions_command,
    uses_production_compose,
)
from ._module_scaffold import (
    scaffold_community_module,  # noqa: F401  — re-exported for backward compatibility
)

console = Console()


# ---------------------------------------------------------------------------
# Source resolution (local path or git URL)
# ---------------------------------------------------------------------------


def _is_git_source(source: str) -> bool:
    return source.endswith('.git') or source.startswith(('https://', 'git@', 'http://'))


def _reject_option_like(value: str, label: str) -> None:
    """Refuse a value git would read as a flag.

    ``git checkout --detach <rev>`` takes the rev positionally, and ``--`` is
    not a fix there: it separates *pathspecs*, so ``checkout --detach -- <rev>``
    treats the rev as a path and fails. Screening the input is the only place
    this can be closed.
    """
    if value.startswith('-'):
        raise OperatorError(f'{label} may not start with "-": {value!r}')


def _clone_at_rev(source: str, rev: str, tmp: Path) -> None:
    """Clone *source* into *tmp* and check out exactly *rev*.

    Tries a shallow clone of the ref first (works for tags and branches), and
    falls back to a full clone plus checkout, which is the only thing that
    works for a bare commit SHA on servers that refuse to serve arbitrary
    objects.
    """
    _reject_option_like(rev, 'Revision')
    _reject_option_like(source, 'Source')

    shallow = subprocess.run(
        ['git', 'clone', '--depth=1', '--branch', rev, '--', source, str(tmp)],
        capture_output=True,
        text=True,
    )
    if shallow.returncode == 0:
        return

    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    full = subprocess.run(
        ['git', 'clone', '--', source, str(tmp)], capture_output=True, text=True
    )
    if full.returncode != 0:
        raise OperatorError(f'git clone failed:\n{full.stderr}')

    checkout = subprocess.run(
        ['git', '-C', str(tmp), 'checkout', '--detach', rev],
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        # Not the checkout's stderr: an unknown rev makes git argue about a
        # path argument to --detach, which reads as a problem the user never
        # caused. Say what is missing and how to look, and stop there.
        raise OperatorError(
            f'Revision {rev!r} not found in {source}. '
            f'Check what the remote offers: git ls-remote --tags {source}'
        )


def resolve_source(
    source: str, rev: str | None = None
) -> tuple[Path, bool, str | None]:
    """Resolve *source* to a local Path.

    Returns (path, is_tmp, commit) where is_tmp=True means the caller should
    clean up, and *commit* is the SHA that was checked out (``None`` for local
    directories). Supports local directory paths and git HTTPS/SSH URLs.

    A git source requires *rev*: installing whatever happens to be on the
    default branch means two installs of "the same" module can differ, and
    there is nothing to audit afterwards.
    """
    if _is_git_source(source):
        if not rev:
            raise OperatorError(
                'Installing from git requires a pinned revision: pass --rev <tag|commit>. '
                'Without it the installed code depends on when you ran the command.'
            )
        tmp = Path(tempfile.mkdtemp(prefix='inventari_module_'))
        console.print(f'[blue]Cloning {source} at {rev}...[/]')
        try:
            _clone_at_rev(source, rev, tmp)
        except ValueError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        commit = subprocess.run(
            ['git', '-C', str(tmp), 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return tmp, True, commit or None

    local = Path(source).expanduser().resolve()
    if not local.exists() or not local.is_dir():
        raise OperatorError(
            f'Source path does not exist or is not a directory: {source}'
        )
    return local, False, None


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install_module(
    source: str,
    rev: str | None = None,
    *,
    signature_file: Path | None = None,
    allow_unsigned: bool = False,
) -> None:
    """Install a community module from *source* (local path or git URL)."""
    source_dir, is_tmp, commit = resolve_source(source, rev)
    try:
        _do_install(
            source_dir,
            original_source=source,
            source_rev=rev,
            source_commit=commit,
            signature_file=signature_file,
            allow_unsigned=allow_unsigned,
        )
    finally:
        if is_tmp:
            shutil.rmtree(source_dir, ignore_errors=True)


def _check_install_guards(
    meta: ModuleYaml, name: str, source_dir: Path
) -> dict[str, TrackingEntry]:
    """Refuse the install before a single file is copied.

    Returns the tracking file, which the caller updates once the copy lands.
    """
    # 1b. Guard: platform version compatibility
    version_error = check_min_version(meta['inventari_min_version'])
    if version_error:
        console.print(f"[red]✗ Module '{name}' {version_error}.[/]")
        raise SystemExit(1)

    # 2. Guard: reserved names
    refusal = _reserved_name_refusal(name)
    if refusal is not None:
        console.print(f'[red]✗ {refusal}[/]')
        raise SystemExit(1)

    # 3. Guard: path traversal
    if not _VALID_NAME_RE.match(name):
        console.print(f'[red]✗ Module name {name!r} is not safe.[/]')
        raise SystemExit(1)

    # 4. Guard: already installed
    tracking = _load_tracking()
    if name in tracking:
        console.print(
            f"[red]✗ Module '{name}' is already installed (v{tracking[name]['version']}).[/]"
        )
        # Sending people to uninstall used to be sending them through a
        # DROP TABLE: that is what the default on_uninstall hook did, and
        # there was no other route between two versions.
        console.print(
            f'[red]  To move to another version: [bold]module upgrade <source>[/bold] '
            f'(keeps the data). To remove it: [bold]module uninstall {name}[/bold].[/]'
        )
        raise SystemExit(1)

    # 5. Guard: in-tree collision, on either side. A module's frontend lands
    # beside the core's own directories under frontend/src/modules/, and a
    # tree already standing there is either the core's or a leftover nobody
    # tracks — writing into it would overwrite files the install does not own.
    if (BACKEND_MODULES_DIR / name).exists():
        console.print(
            f'[red]✗ Directory backend/app/modules/{name} already exists and is not tracked '
            f'as a community module. Aborting to avoid overwriting unexpected data.[/]'
        )
        raise SystemExit(1)
    if (FRONTEND_MODULES_DIR / name).exists():
        console.print(
            f'[red]✗ Directory frontend/src/modules/{name} already exists and is not tracked '
            f'as a community module. Aborting to avoid overwriting unexpected data.[/]'
        )
        raise SystemExit(1)

    # 6. Dependency check
    for dep in meta['requires']:
        dep_backend = BACKEND_MODULES_DIR / dep
        dep_in_tracking = dep in tracking
        if not dep_backend.exists() and not dep_in_tracking:
            console.print(f"[red]✗ Required module '{dep}' is not installed.[/]")
            raise SystemExit(1)

    # 7. Validate source directories exist
    components = (
        (meta['components'].get('backend', True), 'backend'),
        (meta['components'].get('frontend', True), 'frontend'),
    )
    for declared, component in components:
        if declared and not (source_dir / component).exists():
            console.print(
                f'[red]✗ module.yaml declares {component}=true but no '
                f'{component}/ directory found.[/]'
            )
            raise SystemExit(1)

    return tracking


def _merge_yaml_metadata_into_manifest(dest_backend: Path, meta: ModuleYaml) -> None:
    """Write module.yaml's identity fields into the copied manifest.json.

    The registry reads manifest.json only, and the scaffold puts the fields the
    author is told to edit (author, description, license, homepage) in
    module.yaml — copying the backend tree verbatim dropped them, so every
    community module introduced itself to the store as the core team with an
    empty description. module.yaml wins wherever it says something ('unknown'
    is the parser's placeholder for an absent author, not an author); the
    manifest's own values stand otherwise.
    """
    manifest_path = dest_backend / 'manifest.json'
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    author = meta.get('author', '')
    if author and author != 'unknown':
        manifest['author'] = author
    if meta.get('description'):
        manifest['description'] = meta['description']
    if meta.get('license'):
        manifest['license'] = meta['license']
    if meta.get('homepage'):
        manifest['homepage'] = meta['homepage']
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def _validate_copied_backend(dest_backend: Path) -> None:
    """Run AST safety validation on the files that were just copied.

    Called only after the caller has recorded the copy, so a failure here is
    still rolled back.
    """
    console.print('  Running AST safety validation...')
    violations = _run_ast_validation(dest_backend)
    if violations:
        console.print('[red]✗ Safety validation failed:[/]')
        for v in violations:
            console.print(f'    [red]- {v}[/]')
        raise RuntimeError('Safety validation failed')

    # A package discovery cannot import is rejected at the next start, after
    # the installer has said "installed successfully" — refused here instead,
    # while the files can still be rolled back.
    from app.cli.module_validator import validate_importable

    console.print('  Importing the backend package...')
    unimportable = validate_importable([dest_backend])
    if unimportable:
        console.print('[red]✗ The backend package cannot be imported:[/]')
        for failure in unimportable:
            console.print(f'    - {failure}', style='red', markup=False)
        raise RuntimeError('the backend package cannot be imported')

    console.print('  [green]✓ Backend validation passed.[/]')

    # A deprecated method still works until its removal release — the
    # install refuses nothing and names the migration debt the author
    # owes, the same lines `module validate` reports.
    from app.cli.module_validator import (
        validate_deprecated_core_api,
        validate_manifest_icon,
        validate_permission_actions,
    )

    for finding in validate_deprecated_core_api(dest_backend):
        console.print(f'  [yellow]![/] {finding}')

    # An icon outside the catalogue's list is drawn as a generic package: the
    # module installs, and the author is told which name to change.
    for finding in validate_manifest_icon(dest_backend):
        console.print(f'  [yellow]![/] {finding}')

    # So is a permission action outside the vocabulary: the key works, and
    # renaming it later means a migration over every organization's roles.
    for finding in validate_permission_actions(dest_backend):
        console.print(f'  [yellow]![/] {finding}')


def _refuse_unwritable_module_trees(*, backend: bool, frontend: bool) -> None:
    """Stop before copying when a mounted module tree is not writable.

    The production compose file mounts these trees from the deployment
    checkout, which belongs to whoever cloned it — ``root`` included — while
    the installer runs as the image's ``appuser``. A raw ``EACCES`` halfway
    through the copy names neither the cause nor the one command that fixes
    it, so the refusal carries the remedy instead. The frontend tree is only
    checked when it exists: a missing one has its own warning and a supported
    backend-only install, and a directory the copy creates is checked through
    its parent by the copy itself.
    """
    trees = [BACKEND_MODULES_DIR] if backend else []
    if frontend and FRONTEND_MODULES_DIR.exists():
        trees.append(FRONTEND_MODULES_DIR)
    unwritable = [
        tree for tree in trees if tree.exists() and not os.access(tree, os.W_OK)
    ]
    if not unwritable:
        return

    for tree in unwritable:
        console.print(
            f'[red]✗ The module installer (uid {os.geteuid()}) cannot write {tree}.[/]'
        )
    if uses_production_compose():
        console.print(
            '[red]  The deployment checkout can belong to a different user than '
            "the one the installer runs as. Give the container's user write "
            'access to the mounted trees, then run the command again:[/]'
        )
        console.print(f'  {module_tree_permissions_command()}', soft_wrap=True)
    else:
        console.print(
            '[red]  Make this directory writable by the user running the '
            'installer, then run the command again.[/]'
        )
    raise SystemExit(1)


def _copy_module_files(
    name: str,
    source_dir: Path,
    *,
    meta: ModuleYaml,
    has_backend: bool,
    has_frontend: bool,
) -> tuple[bool, bool]:
    """Copy the declared components, rolling both back if either fails.

    Returns which halves actually landed — the frontend one is skipped rather
    than failed when the frontend tree is not mounted in this container.
    """
    _refuse_unwritable_module_trees(backend=has_backend, frontend=has_frontend)
    dest_backend = BACKEND_MODULES_DIR / name
    dest_frontend = FRONTEND_MODULES_DIR / name
    copied_backend = False
    copied_frontend = False

    try:
        # One enumeration for the digest and this copy (package_walk), so
        # what was verified is — file for file — what lands on disk. Both
        # halves drop tests/ (the author's workbench, not runtime code: a
        # payload under backend/tests/ would land importable as
        # app.modules.<name>.tests.<file>, and one under frontend/tests/
        # would be collected by the repository's own vitest run) and
        # __pycache__ bytecode; symlinks are refused at the walk. What the
        # walk dropped is named below rather than left to be discovered.
        from ._module_signing import package_walk

        walked, dropped = package_walk(source_dir, meta)
        shipped = [path for path in walked if path.name != 'module.yaml']
        if dropped:
            console.print(
                f'  [yellow]⚠ {len(dropped)} file(s) under a tests/ directory are not '
                f'installed — tests are the workbench and never ship:[/]'
            )
            for path in dropped:
                console.print(
                    f'    [yellow]- {path.relative_to(source_dir).as_posix()}[/]'
                )
        backend_files = [
            path
            for path in shipped
            if path.relative_to(source_dir).parts[0] == 'backend'
        ]
        frontend_files = [
            path
            for path in shipped
            if path.relative_to(source_dir).parts[0] == 'frontend'
        ]

        if has_backend:
            console.print(f'  Copying backend → backend/app/modules/{name}/')
            for path in backend_files:
                rel = path.relative_to(source_dir / 'backend')
                dest = dest_backend / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
            copied_backend = True

            # 9. AST safety validation on the copied files
            _validate_copied_backend(dest_backend)

            # The manifest is what the registry reads; the author's identity
            # fields live in module.yaml. Landing inside the try keeps a
            # manifest rewrite failure inside the rollback.
            _merge_yaml_metadata_into_manifest(dest_backend, meta)

        if has_frontend:
            # The question is not whether a frontend/ tree exists somewhere but
            # whether this process can write a module into it. On the dev stack
            # docker-compose bind-mounts it; a deployment compose file does not,
            # and there the install belongs on the host.
            if not FRONTEND_MODULES_DIR.exists():
                console.print(
                    f'[yellow]⚠ The frontend module tree is not reachable from here '
                    f'({FRONTEND_MODULES_DIR}), so this module installed without its '
                    f'screens.[/]'
                )
                console.print(
                    '[yellow]  Run the install on the host with '
                    'INVENTARI_PROJECT_ROOT=/path/to/inventari, or mount the tree and '
                    'point INVENTARI_FRONTEND_MODULES_DIR at the mount.[/]'
                )
            else:
                console.print(f'  Copying frontend → frontend/src/modules/{name}/')
                for path in frontend_files:
                    rel = path.relative_to(source_dir / 'frontend')
                    dest = dest_frontend / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                copied_frontend = True
                console.print('  [green]✓ Frontend files copied.[/]')

    except Exception as exc:  # rollback must cover every failure, copy errors included
        # Rollback: remove anything that was already copied
        if copied_backend and dest_backend.exists():
            shutil.rmtree(dest_backend)
            console.print(f'  [yellow]↩ Rolled back backend/app/modules/{name}/[/]')
        if copied_frontend and dest_frontend.exists():
            shutil.rmtree(dest_frontend)
            console.print(f'  [yellow]↩ Rolled back frontend/src/modules/{name}/[/]')
        console.print(f'[red]✗ Installation aborted: {exc}[/]')
        raise SystemExit(1) from exc

    return copied_backend, copied_frontend


def _print_next_steps(
    name: str, *, copied_backend: bool, copied_frontend: bool, frontend_missing: bool
) -> None:
    console.print('')
    console.print('[yellow]Next steps:[/]')
    # The commands depend on the stack that ran the install, not on the one
    # the author happens to use: the production frontend is nginx with no
    # npm in it, and a bare `docker compose` there starts the development
    # stack instead of the deployment.
    for command in deployment_steps(backend=copied_backend, frontend=copied_frontend):
        # soft_wrap: a wrapped line is still copyable, but an operator reading
        # it learns the wrong command boundary.
        console.print(f'  {command}', soft_wrap=True)
    if frontend_missing:
        # The work that is left belongs here, next to the work that is done —
        # a warning printed further up scrolls past and reads as advice.
        console.print(
            '  [yellow]This module ships screens that did not install, so it '
            'will run with no interface.[/]'
        )
        console.print(
            '  [yellow]Make the frontend module tree reachable (MODULES_GUIDE, '
            '"Install a community module"), then:[/]'
        )
        manage = f'{compose_command()} exec backend python manage.py'
        console.print(f'    {manage} module uninstall {name}')
        console.print(f'    {manage} module install <same source>')


def _verify_package_signature(
    source_dir: Path,
    meta: ModuleYaml,
    *,
    signature_file: Path | None,
    allow_unsigned: bool,
) -> dict[str, str]:
    """Decide what this deployment thinks of the package's signature.

    Runs before a single file is copied. Three outcomes, handled
    separately on purpose: a verified signature records who signed it;
    an *unsigned* package — no signature file at all — installs only
    after the explicit switch, with the risk named; an *invalid*
    verification (tampered content, untrusted key, unreadable signature)
    is evidence of a problem, not the absence of one, and no switch
    accepts it. ``signature_verified_at`` is written only for a verified
    package — a timestamp on an unsigned record would describe a
    verification that never happened.
    """
    from ._module_signing import verify_module_signature

    result = verify_module_signature(source_dir, meta, signature_file)

    if result.outcome == 'verified':
        console.print(
            f'  [green]✓ Signature verified (signing key {result.key_id}).[/]'
        )
        return {
            'signature_status': 'verified',
            'signature_key_id': result.key_id or 'unknown',
            'signature_verified_at': datetime.now(UTC).isoformat(),
        }

    if result.outcome == 'invalid':
        if result.missing_trusted_keys:
            # The package is signed and the content may be unmodified; this
            # installation has no key to say either way. The publisher has
            # nothing to fix — the operator has one line to add.
            console.print(
                '[red]✗ Refusing to install: this deployment trusts no module '
                "signing keys, so it cannot vouch for the publisher's "
                'signature.[/]'
            )
            console.print(
                f"[red]  Add the publisher's key to MODULE_SIGNING_PUBLIC_KEYS "
                f'(key_id=<base64 public key>, comma- or newline-separated) in '
                f"this installation's environment, recreate the backend "
                f'container ({compose_command()} up -d backend), and run the '
                f'install again.[/]'
            )
        else:
            console.print(
                f'[red]✗ Refusing to install a package with an invalid signature: '
                f'{result.reason}.[/]'
            )
            console.print(
                '[red]Module code runs in-process with full access to this '
                'installation, and a bad signature means the content does not '
                'match whatever was signed, or the signer is not trusted. There '
                'is no switch for this: re-sign the package and reinstall.[/]'
            )
        raise SystemExit(1)

    # outcome == 'unsigned': the package carries no signature file at all.
    if allow_unsigned:
        console.print('[yellow]⚠ Installing an UNSIGNED module.[/]')
        console.print(
            '[yellow]  Unsigned module code is not attributable to anyone who '
            'reviewed it, and it runs in-process with full access to the '
            'database and the filesystem.[/]'
        )
        return {
            'signature_status': 'unsigned',
            'signature_key_id': '',
        }

    console.print('[red]✗ Refusing to install an unsigned package.[/]')
    console.print(
        '[red]Module code runs in-process with full access to this installation. '
        'Install a package signed by a key listed in MODULE_SIGNING_PUBLIC_KEYS '
        '(see `module sign`), or pass --allow-unsigned to accept the risk '
        'explicitly.[/]'
    )
    raise SystemExit(1)


def _do_install(
    source_dir: Path,
    *,
    original_source: str,
    source_rev: str | None = None,
    source_commit: str | None = None,
    signature_file: Path | None = None,
    allow_unsigned: bool = False,
) -> None:
    # 1. Parse module.yaml
    try:
        meta = _parse_module_yaml(source_dir)
    except ValueError as exc:
        if not (source_dir / 'module.yaml').exists():
            # The temp clone is gone by the time this prints — name the place
            # the user pointed at, not the scratch directory it unpacked to.
            at_rev = f' at revision {source_rev}' if source_rev else ''
            console.print(
                f'[red]✗ module.yaml not found in {original_source}{at_rev}.[/]'
            )
        else:
            console.print(f'[red]✗ Invalid module.yaml: {exc}[/]')
        raise SystemExit(1) from exc

    name = meta['name']

    console.print(
        f"[blue]Installing module '[bold]{name}[/bold]' v{meta['version']}...[/]"
    )

    # 1a. Signature verification — before a single file is copied, so a
    # tampered package never reaches the AST validator, let alone the
    # module tree.
    signature_record = _verify_package_signature(
        source_dir,
        meta,
        signature_file=signature_file,
        allow_unsigned=allow_unsigned,
    )

    tracking = _check_install_guards(meta, name, source_dir)

    declares_frontend = meta['components'].get('frontend', True)

    # 8. Copy (backend to its final location, validated in place, rolled back on failure)
    copied_backend, copied_frontend = _copy_module_files(
        name,
        source_dir,
        meta=meta,
        has_backend=meta['components'].get('backend', True),
        has_frontend=declares_frontend,
    )

    # 10. Update tracking file
    tracking[name] = TrackingEntry(
        version=meta['version'],
        source=original_source,
        **({'source_rev': source_rev} if source_rev else {}),
        **({'source_commit': source_commit} if source_commit else {}),
        installed_at=datetime.now(UTC).isoformat(),
        has_backend=copied_backend,
        has_frontend=copied_frontend,
        declares_frontend=declares_frontend,
        requires=meta.get('requires', []),
        inventari_min_version=meta['inventari_min_version'],
        signature_status=signature_record['signature_status'],
        signature_key_id=signature_record['signature_key_id'],
        signature_verified_at=signature_record.get('signature_verified_at'),
    )
    _save_tracking(tracking)

    # A module that declared screens and did not get them is not installed —
    # it is half installed, and the half that is missing is the one the user
    # would have gone looking for.
    frontend_missing = declares_frontend and not copied_frontend

    if frontend_missing:
        console.print(
            f'\n[yellow]⚠ Module [bold]{name}[/bold] v{meta["version"]} installed '
            f'without its frontend.[/]'
        )
    else:
        console.print(
            f'\n[green]✓ Module [bold]{name}[/bold] v{meta["version"]} installed successfully![/]'
        )

    _print_next_steps(
        name,
        copied_backend=copied_backend,
        copied_frontend=copied_frontend,
        frontend_missing=frontend_missing,
    )

    if frontend_missing:
        # The backend half is on disk and tracked, so this is not a rollback —
        # it is a job left unfinished, and a caller that scripts installs has
        # to be able to tell the difference between that and a whole one.
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def uninstall_module(
    name: str, *, force: bool = False, drop_data: bool = False
) -> None:
    """Remove a previously installed community module.

    By default this removes code, not data. The module's tables stay
    exactly as they are, and what the uninstall would leave behind is
    counted and printed first, so the operator decides with the numbers
    in hand.

    ``drop_data=True`` runs the module's ``on_uninstall`` hook, whose
    default implementation downgrades the module's migrations to base —
    ``DROP TABLE`` on every table the module owns, for every organization
    on this installation. That used to be what an uninstall did, behind a
    prompt that spoke only about files. It is now an explicit choice,
    confirmed by typing the word ``data``.
    """

    # 1. Guard: not a core module
    if name in _get_reserved_module_names():
        console.print(
            f"[red]✗ '{name}' is a core module and cannot be uninstalled via this command.[/]"
        )
        raise SystemExit(1)

    # 2. Guard: must be tracked
    tracking = _load_tracking()
    if name not in tracking:
        console.print(
            f"[red]✗ Module '{name}' is not tracked as a community module. "
            f'Use [bold]module list[/bold] to see installed modules.[/]'
        )
        raise SystemExit(1)

    entry = tracking[name]

    # 3. Reverse dependency check
    dependents = [
        mod
        for mod, data in tracking.items()
        if mod != name and name in _load_module_yaml_requires(mod, tracking)
    ]
    if dependents:
        console.print(
            f"[red]✗ Cannot uninstall '{name}': the following modules depend on it:[/]"
        )
        for dep in dependents:
            console.print(f'    - {dep}')
        console.print('  Uninstall those modules first.')
        raise SystemExit(1)

    # 4. What stays behind, counted while the module's files are still on
    # disk (the table names come from its models) and before anything is
    # asked of the operator.
    _print_orphan_report(name, drop_data=drop_data)

    # 5. Confirmation. Two different questions, because they have two
    # different answers: removing code is reversible by reinstalling,
    # dropping the tables is not reversible at all.
    if not force:
        _confirm_uninstall(name, drop_data=drop_data)
    elif drop_data:
        # --force skips the type-'data' gate; the operator gets told so
        # BEFORE anything is removed, not in a summary line afterwards.
        console.print(
            f"[red]--force: skipping the type-'data' confirmation. This will "
            f'DROP every table module {name!r} owns, with the data of every '
            f'organization on this installation. This cannot be undone.[/]'
        )

    # 6. Run the module's on_uninstall hook BEFORE deleting files —
    # only when the operator asked for the data to go. The default hook
    # downgrades the module's migrations to base; a custom hook may add
    # its own cleanup. A hook failure aborts the uninstall so the files
    # and the database stay consistent.
    dest_backend = BACKEND_MODULES_DIR / name
    dest_frontend = FRONTEND_MODULES_DIR / name
    # Removing the files needs the same write access as installing them. Check
    # before the on_uninstall hook: a data drop that runs and then cannot
    # remove the code leaves the module half-uninstalled.
    if dest_backend.exists() or dest_frontend.exists():
        _refuse_unwritable_module_trees(
            backend=dest_backend.exists(), frontend=dest_frontend.exists()
        )

    tables_dropped = False
    hook_skipped = False
    module_tables: list[str] = []
    tables_left: list[str] | None = None
    if drop_data and entry.get('has_backend', True) and dest_backend.exists():
        # Named while the files are still on disk. After the hook they are
        # how the summary asks the database what the drop actually did —
        # the hook's return value only says it came back without an
        # exception, which a downgrade that skipped or dropped nothing
        # also does.
        module_tables = sorted(_module_table_names(name))
        tables_dropped = _run_on_uninstall_hook(name)
        hook_skipped = not tables_dropped
        if tables_dropped:
            tables_left = _tables_still_present(module_tables)

    # 7. Delete files
    if entry.get('has_backend', True) and dest_backend.exists():
        shutil.rmtree(dest_backend)
        console.print(f'  Removed backend/app/modules/{name}/')

    if entry.get('has_frontend', True) and dest_frontend.exists():
        shutil.rmtree(dest_frontend)
        console.print(f'  Removed frontend/src/modules/{name}/')

    # 8. Update tracking
    del tracking[name]
    _save_tracking(tracking)

    # 9. Forget the installation record, so installing this module again is
    # an installation and not a no-op. The registry decides whether to run
    # ``on_install`` by comparing the module's version against this row; a
    # row left behind means a reinstall of the same version runs no install
    # hook at all — no seed, no defaults, no per-module setup — while the
    # entrypoint's ``db upgrade-modules`` quietly recreates the tables. The
    # module comes back looking installed and behaving like it never was.
    _forget_installation_record(name)

    console.print(f'\n[green]✓ Module [bold]{name}[/bold] uninstalled.[/]')
    _print_drop_summary(
        drop_data=drop_data,
        hook_skipped=hook_skipped,
        module_tables=module_tables,
        tables_left=tables_left,
        tables_dropped=tables_dropped,
    )
    console.print('[yellow]Next steps:[/]')
    for command in deployment_steps(
        backend=True, frontend=bool(entry.get('has_frontend', True))
    ):
        console.print(f'  {command}', soft_wrap=True)


def _print_drop_summary(
    *,
    drop_data: bool,
    hook_skipped: bool,
    module_tables: list[str],
    tables_left: list[str] | None,
    tables_dropped: bool,
) -> None:
    """Speak about the drop the way the schema, not the hook, answered.

    "The hook ran" is not evidence of a drop — a skipped downgrade and an
    empty ``downgrade()`` both return without an exception — so every
    branch here is derived from what was actually checked, and a claim
    nobody checked stays unspoken.

    The tables-survive branch keeps a green exit on purpose: the files are
    already gone, so a non-zero exit would change nothing on disk or in
    the database, while the operator still gets the truth, the named
    survivors, and the command to finish the job by hand. Exit codes
    answer "did the uninstall complete"; this summary answers "what did
    it actually do".
    """
    if drop_data and hook_skipped:
        # The files are gone but the hook never ran: the module was not in
        # the registry (a rejected import, typically a broken module.py),
        # so its migration downgrade — the thing that drops the tables —
        # did not happen either. Claiming "dropped" here would contradict
        # the database two lines below the promise.
        console.print(
            '[yellow]Its tables and their data were NOT dropped: the module '
            'never loaded into the registry, so the drop-hook could not run. '
            'The files are removed; the schema is still there. Fix the module '
            'and uninstall it again to drop the tables, or remove them by '
            'hand with `python manage.py db`.[/]'
        )
    elif drop_data and tables_left is None and module_tables:
        # The hook ran, but the schema could not be read afterwards, so
        # the drop is unverified. Saying "dropped" here would celebrate
        # something nobody checked.
        console.print(
            '[yellow]The drop-hook ran, but the summary could not read the '
            "schema to verify the drop. Check the module's tables by hand "
            'with `python manage.py db` before reinstalling.[/]'
        )
    elif drop_data and tables_left:
        # The hook ran clean, but the database still holds tables the
        # module owns: a missing migrations directory skips the downgrade
        # quietly and an empty downgrade() drops nothing, both returning
        # without an exception. The operator asked for the data to go —
        # the summary names what actually survived it.
        console.print(
            f'[yellow]The drop-hook ran, but {len(tables_left)} of its table(s) '
            f'are still in the database: {", ".join(tables_left)}. The '
            "module's downgrade did not drop them — remove them by hand "
            'with `python manage.py db` before reinstalling.[/]'
        )
    elif drop_data and tables_dropped and module_tables:
        # The set is named and the schema says it is gone — the one shape
        # where "dropped" is a claim somebody verified.
        console.print('[yellow]Its tables and their data were dropped.[/]')
    elif drop_data and tables_dropped:
        # The hook ran, but no table names were ever collected (the
        # collector reads __tablename__ and create_table, not every way a
        # migration can make a table). "Dropped" about a set nobody could
        # list verifies nothing — the claim is withheld, not softened.
        console.print(
            '[yellow]The drop-hook ran, but the module owns no tables this '
            'tool could name, so the drop is unverified. Check what remains '
            'by hand with `python manage.py db` before reinstalling.[/]'
        )
    elif drop_data:
        # The backend files were already gone, so no hook ran and no table
        # was touched. Saying "dropped" here was a lie the operator could
        # only catch by checking the database afterwards.
        console.print(
            "[yellow]Its tables were not touched: the module's backend files "
            'were already gone, so there was nothing to run the drop against. '
            'Inspect what remains with `python manage.py db` if in doubt.[/]'
        )
    else:
        console.print(
            '[green]Its tables and their data were kept — reinstalling the module '
            'picks them up where they are.[/]'
        )


def _print_orphan_report(name: str, *, drop_data: bool) -> None:
    """Print what this uninstall leaves behind (or is about to destroy).

    The counts are the same either way; what changes is what they mean.
    Without ``--drop-data`` they are what survives, and the report is
    reassurance plus a to-do list. With it, the module's own tables are
    what is being dropped, and the rest still survives — orphaned, this
    time for real, because the code that could interpret it is gone.
    """
    from ._module_orphans import collect_orphans

    report = collect_orphans(name)
    groups = list(report.groups)
    if report.failures:
        # An unchecked report and an empty one are different answers, and
        # the operator decides whether to add --drop-data on the strength
        # of this line. It said "No stored data was found" when the probe
        # had never run, which is the one thing the line must not do.
        console.print(
            f"[red]Could not check what module '{name}' leaves behind: a "
            'check failed. That is not the same as the module having '
            'stored nothing.[/]'
        )
        for failure in report.failures:
            console.print(f'  - {failure}', markup=False)
        if not groups:
            return
        console.print('[yellow]The list below is incomplete.[/]')
    elif not groups:
        console.print(f"  No stored data was found for module '{name}'.")
        return

    def _lines(selected: list, *, dropped: bool = False) -> None:
        for group in selected:
            console.print(f'  • [bold]{group.reads_as()}[/bold]')
            console.print(f'      {(dropped and group.where_dropped) or group.where}')
            for detail in group.names:
                console.print(f'      - {detail}')

    console.print('')
    if not drop_data:
        console.print(f"[blue]What stays behind when '{name}' is removed:[/]")
        _lines(groups)
        console.print('')
        return

    doomed = [g for g in groups if g.goes_with_drop_data]
    surviving = [g for g in groups if not g.goes_with_drop_data]
    if doomed:
        console.print('[red]--drop-data will destroy, for every organization:[/]')
        _lines(doomed, dropped=True)
    if surviving:
        # The flag drops the module's schema and nothing else. Everything
        # here outlives it, and now without the code that could read it.
        console.print('[yellow]Left behind even with --drop-data:[/]')
        _lines(surviving)
    console.print('')


def _confirm_uninstall(name: str, *, drop_data: bool) -> None:
    """Ask before removing, and ask differently when data is at stake.

    A yes/no prompt is the right weight for "remove the code". It is the
    wrong weight for "drop every table this module owns, for every
    organization on this installation", which is why that one is not a
    yes/no at all: the operator types the word ``data``, which cannot be
    hit by reflex or by a stray newline in a script.
    """
    import typer

    if not drop_data:
        confirmed = typer.confirm(
            f"Remove the files of module '{name}'? Its tables and their data "
            f'will be kept.'
        )
        if not confirmed:
            console.print('[yellow]Uninstall cancelled.[/]')
            raise SystemExit(0)
        return

    console.print(
        f"[red]--drop-data will DROP every table module '{name}' owns, with the "
        f'data of every organization on this installation. This cannot be '
        f'undone: a reinstall brings back empty tables.[/]'
    )
    typed = typer.prompt("Type the word 'data' to confirm, anything else to cancel")
    if typed.strip().lower() != 'data':
        console.print('[yellow]Uninstall cancelled — nothing was removed.[/]')
        raise SystemExit(0)


def _forget_installation_record(name: str) -> None:
    """Delete the ``module_installations`` row for *name*.

    Without this, the row outlives the module and the next install of the
    same version is read as "already installed": ``on_install`` never
    runs. The row is bookkeeping about a module that is no longer here, so
    it goes with the module. A database that cannot be reached is a
    warning and not a failed uninstall — the files are already gone.
    """
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from app.database import SessionLocal
        from app.models.module_installation import ModuleInstallation

        with SessionLocal() as db:
            deleted = (
                db.query(ModuleInstallation)
                .filter(ModuleInstallation.module_name == name)
                .delete()
            )
            db.commit()
        if deleted:
            console.print(
                '  Cleared the installation record (reinstall runs on_install).'
            )
    except SQLAlchemyError as exc:
        console.print(
            f'[yellow]⚠ Could not clear the installation record for {name!r}: {exc}[/]'
        )
        console.print(
            '[yellow]  Reinstalling the same version will skip its on_install hook '
            "until that row is gone (table 'module_installations').[/]"
        )


def _module_table_names(name: str) -> set[str]:
    """Tables the module owns, read from its models and migrations.

    Collected while the module's files are still on disk — after the
    uninstall there is nothing left to read them from, and they are what
    the summary checks the database against.
    """
    from app.core.architecture_lint._quality_checks import (
        _collect_module_tablenames,
    )

    return _collect_module_tablenames(BACKEND_MODULES_DIR / name)


def _tables_still_present(table_names: list[str]) -> list[str] | None:
    """Which of the module's tables the database still holds.

    Asked after the drop-hook ran, because the hook's return value only
    says it came back without an exception. ``None`` means the schema
    could not be read at all — the caller then refuses to claim a drop
    it did not verify.
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from app.cli.commands_db import _migration_db_url

        url = _migration_db_url().replace('postgresql+asyncpg', 'postgresql')
        engine = create_engine(url)
        try:
            existing = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
    except SQLAlchemyError as exc:
        console.print(
            f'[yellow]⚠ Could not read the schema to verify the drop: {exc}[/]'
        )
        return None

    return [t for t in table_names if t in existing]


def _run_on_uninstall_hook(name: str) -> bool:
    """Invoke the module's ``on_uninstall`` hook.

    The default hook downgrades the module's Alembic migrations to base.
    A hook failure aborts the uninstall (files are left in place) so the
    module code and the database schema stay consistent.

    Returns whether the hook actually ran — ``False`` when the module
    never made it into the registry, which is exactly the case where the
    drop did not happen and the summary must not claim it did.
    """
    from app.core.context import ModuleContext
    from app.core.events import event_bus
    from app.core.module_identity import module_scope
    from app.core.module_registry import module_registry

    module = module_registry.get(name)
    if module is None:
        console.print(
            f'[yellow]⚠ Module {name!r} not found in the registry — '
            f'skipping on_uninstall hook.[/]'
        )
        # The caller must know the hook did not run: its summary says
        # whether the tables were dropped, and only this boolean connects
        # that sentence to what actually happened.
        return False

    console.print('  Running on_uninstall hook (migration downgrade)...')
    try:
        with module_scope(name):
            module.on_uninstall(ModuleContext(event_bus=event_bus))
    except Exception as exc:  # any hook failure aborts the uninstall
        console.print(f'[red]✗ on_uninstall hook failed: {exc}[/]')
        console.print('[red]Uninstall aborted — module files left in place.[/]')
        raise SystemExit(1) from exc
    return True


def _load_module_yaml_requires(
    module_name: str,
    tracking: dict[str, TrackingEntry] | None = None,
) -> list[str]:
    """Read requires list from a module's tracking entry, if available."""
    if tracking is None:
        tracking = _load_tracking()
    entry = tracking.get(module_name)
    return list(entry.get('requires', [])) if entry else []


# ---------------------------------------------------------------------------
# List community modules
# ---------------------------------------------------------------------------


def list_community_modules() -> list[tuple[str, TrackingEntry]]:
    """Return a list of (name, entry) tuples from the tracking file."""
    return list(_load_tracking().items())
