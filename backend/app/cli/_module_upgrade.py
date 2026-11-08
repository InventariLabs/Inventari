"""Upgrading an installed community module in place.

Before this, the only way from v0.1 to v0.2 was uninstall-then-install,
and the install guard said so out loud ("Run module uninstall first").
That instruction was a data-loss instruction: the uninstall it sent
people to downgraded the module's migrations to base, so the route from
one version to the next ran through ``DROP TABLE``. Nothing in
MODULE_VERSIONING.md or MODULE_QUICKSTART.md mentioned upgrading at
all, which is how a missing command stayed missing.

What an upgrade is, concretely:

- the same verification an install does — a package whose signature does
  not check out does not become trusted by being an upgrade of something
  that was;
- a replacement of the module's files rather than a copy over them, so a
  file that v0.2 dropped does not keep running from v0.1;
- the module's own migrations, run from the newly landed files;
- ``on_upgrade``, which runs at the next boot rather than here — it
  belongs to the new code, and the new code is not the code this process
  imported at startup. Running it now would run v0.1's idea of how to
  migrate from v0.1.

The version in ``module_installations`` is deliberately left alone: it is
what tells the next boot that a bump happened, and thus what makes the
hook run.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from app.core.version import check_min_version, parse_version

from ._module_meta import (
    BACKEND_MODULES_DIR,
    FRONTEND_MODULES_DIR,
    ModuleYaml,
    TrackingEntry,
    _load_tracking,
    _parse_module_yaml,
    _save_tracking,
    _unmet_requirements,
    deployment_steps,
)

console = Console()


def upgrade_module(
    source: str,
    rev: str | None = None,
    *,
    signature_file: Path | None = None,
    allow_unsigned: bool = False,
    force: bool = False,
) -> None:
    """Upgrade an already installed community module from *source*."""
    from .module_packaging import resolve_source

    source_dir, is_tmp, commit = resolve_source(source, rev)
    try:
        _do_upgrade(
            source_dir,
            original_source=source,
            source_rev=rev,
            source_commit=commit,
            signature_file=signature_file,
            allow_unsigned=allow_unsigned,
            force=force,
        )
    finally:
        if is_tmp:
            shutil.rmtree(source_dir, ignore_errors=True)


def _check_upgrade_guards(
    meta: ModuleYaml, name: str, source_dir: Path, *, force: bool
) -> dict:
    """Refuse the upgrade before a single file moves."""
    tracking = _load_tracking()

    if name not in tracking:
        console.print(
            f"[red]✗ Module '{name}' is not installed as a community module. "
            f'Use [bold]module install[/bold] for a first install.[/]'
        )
        raise SystemExit(1)

    version_error = check_min_version(meta['inventari_min_version'])
    if version_error:
        console.print(f"[red]✗ Module '{name}' {version_error}.[/]")
        raise SystemExit(1)

    installed = tracking[name].get('version', '')
    _check_version_direction(name, installed, meta['version'], force=force)

    for dep in _unmet_requirements(
        meta.get('requires', []), tracking, BACKEND_MODULES_DIR
    ):
        console.print(f"[red]✗ Required module '{dep}' is not installed.[/]")
        raise SystemExit(1)

    for declared, component in (
        (meta['components'].get('backend', True), 'backend'),
        (meta['components'].get('frontend', True), 'frontend'),
    ):
        if declared and not (source_dir / component).exists():
            console.print(
                f'[red]✗ module.yaml declares {component}=true but no '
                f'{component}/ directory found.[/]'
            )
            raise SystemExit(1)

    return tracking


def _check_version_direction(
    name: str,
    installed: str,
    incoming: str,
    *,
    force: bool,
) -> None:
    """Refuse an upgrade that is not one, unless the operator insists.

    Reinstalling the same version is a legitimate thing to want (a
    re-deploy of a rebuilt package), and so is going back to the previous
    one after a bad release. Neither should happen by accident, because
    both run the new package's migrations forward and neither is what the
    word "upgrade" led the operator to expect.
    """
    try:
        going_forward = parse_version(incoming) > parse_version(installed)
        same = parse_version(incoming) == parse_version(installed)
    except ValueError:
        # A version string this command cannot compare is not a reason to
        # refuse — the module names its own versions — but it is a reason
        # to say the check did not happen.
        console.print(
            f'[yellow]⚠ Cannot compare versions {installed!r} → {incoming!r}; '
            f'proceeding without a direction check.[/]'
        )
        return

    if going_forward:
        return
    what = 'the version already installed' if same else 'an older version'
    if not force:
        console.print(
            f"[red]✗ Package for '{name}' is {what} "
            f'(installed v{installed}, package v{incoming}).[/]'
        )
        console.print(
            '[red]  Pass --force to install it anyway. Downgrading runs the '
            "older package's migrations forward, which is not the same as "
            'undoing the newer ones.[/]'
        )
        raise SystemExit(1)
    console.print(f'[yellow]⚠ Installing {what} (forced).[/]')


def _swap_module_files(
    name: str, source_dir: Path, meta: ModuleYaml
) -> tuple[bool, bool]:
    """Replace the installed files with the package's, or leave them be.

    The old tree moves aside before the new one lands, so v0.2 does not
    inherit files v0.1 shipped and v0.2 deleted — a stale router or model
    left behind still imports, still registers, still runs. If anything
    about the new copy fails (AST validation included), the old tree moves
    back and the installation is exactly as it was.
    """
    from .module_packaging import _copy_module_files, _refuse_unwritable_module_trees

    dest_backend = BACKEND_MODULES_DIR / name
    dest_frontend = FRONTEND_MODULES_DIR / name
    # Moving a tree aside needs write access to the directory that holds it,
    # exactly like copying into it does; check before the first move so a
    # deployment whose checkout ownership changed gets the remedy instead of
    # EACCES with the installed tree already half-moved.
    _refuse_unwritable_module_trees(
        backend=dest_backend.exists(), frontend=dest_frontend.exists()
    )
    backup_root = Path(tempfile.mkdtemp(prefix=f'inventari_upgrade_{name}_'))
    saved: list[tuple[Path, Path]] = []

    for dest in (dest_backend, dest_frontend):
        if dest.exists():
            keep = backup_root / dest.parent.name / dest.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(keep))
            saved.append((dest, keep))

    try:
        copied = _copy_module_files(
            name,
            source_dir,
            meta=meta,
            has_backend=meta['components'].get('backend', True),
            has_frontend=meta['components'].get('frontend', True),
        )
    except BaseException:  # the previous copy is restored on any exit, then re-raised
        for dest, keep in saved:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(keep), str(dest))
        console.print(f'  [yellow]↩ Restored the previously installed {name}.[/]')
        shutil.rmtree(backup_root, ignore_errors=True)
        raise

    shutil.rmtree(backup_root, ignore_errors=True)
    return copied


def _run_module_migrations_after_upgrade(name: str) -> None:
    """Bring the module's schema to the new package's head.

    The hook that runs at boot (``on_upgrade``) defaults to ``pass`` and no
    module in the tree overrides it, so nothing else in the upgrade path
    would apply a migration the new version shipped. The entrypoint's
    ``db upgrade-modules`` does it on the next container start; doing it
    here means the restart finds the schema already where the new code
    expects it.
    """
    from app.core.module_migrations import module_migrations_dir, run_module_migrations

    try:
        module_migrations_dir(name)
    except FileNotFoundError:
        return

    console.print('  Running module migrations...')
    try:
        run_module_migrations(name, 'upgrade')
    except Exception as exc:  # the operator decides what to do next
        console.print(f'[red]✗ Module migrations failed: {exc}[/]')
        console.print(
            '[red]  The new files are installed, but the upgrade is NOT '
            'recorded: tracking still names the previous version, which is '
            'the one the schema can answer for. Fix the migration and run '
            '[bold]module upgrade[/bold] again — the forward path accepts '
            'it — or [bold]db upgrade-modules[/bold] on the next start.[/]'
        )
        raise SystemExit(1) from exc


def _do_upgrade(
    source_dir: Path,
    *,
    original_source: str,
    source_rev: str | None,
    source_commit: str | None,
    signature_file: Path | None,
    allow_unsigned: bool,
    force: bool,
) -> None:
    from .module_packaging import _verify_package_signature

    try:
        meta = _parse_module_yaml(source_dir)
    except ValueError as exc:
        console.print(f'[red]✗ Invalid module.yaml: {exc}[/]')
        raise SystemExit(1) from exc

    name = meta['name']
    tracking = _check_upgrade_guards(meta, name, source_dir, force=force)
    installed = tracking[name].get('version', '')

    console.print(
        f"[blue]Upgrading module '[bold]{name}[/bold]' "
        f'v{installed} → v{meta["version"]}...[/]'
    )

    signature_record = _verify_package_signature(
        source_dir,
        meta,
        signature_file=signature_file,
        allow_unsigned=allow_unsigned,
    )

    copied_backend, copied_frontend = _swap_module_files(name, source_dir, meta)

    # The record is written only after the new files' migrations succeed:
    # "v0.2.0 installed" must not be true on any surface an operator reads
    # while the schema is still at 0.1.0. Until the record moves, it keeps
    # naming the old version — the one the schema can answer for — and a
    # retry of the same package walks the forward path, so a failed or
    # killed migration leaves nothing to flag and nothing to undo.
    _run_module_migrations_after_upgrade(name)

    declares_frontend = meta['components'].get('frontend', True)
    # Written out in full rather than merged into the old entry: every
    # field here describes the package that just landed, and a field the
    # new source does not have (a --rev that is gone because this install
    # came from a directory) must not be inherited from the old one.
    # ``installed_at`` is the exception -- this installation began then.
    tracking[name] = TrackingEntry(
        version=meta['version'],
        source=original_source,
        **({'source_rev': source_rev} if source_rev else {}),
        **({'source_commit': source_commit} if source_commit else {}),
        installed_at=tracking[name].get('installed_at', datetime.now(UTC).isoformat()),
        has_backend=copied_backend,
        has_frontend=copied_frontend,
        declares_frontend=declares_frontend,
        requires=meta.get('requires', []),
        inventari_min_version=meta['inventari_min_version'],
        signature_status=signature_record['signature_status'],
        signature_key_id=signature_record['signature_key_id'],
        signature_verified_at=signature_record.get('signature_verified_at'),
        previous_version=installed,
        upgraded_at=datetime.now(UTC).isoformat(),
    )
    _save_tracking(tracking)

    console.print(
        f'\n[green]✓ Module [bold]{name}[/bold] upgraded to v{meta["version"]}.[/]'
    )
    console.print(
        '[green]  Data was not touched: the module keeps the tables it had.[/]'
    )
    console.print('')
    console.print('[yellow]Next steps:[/]')
    # Same split as the install: the production frontend is an image to
    # rebuild, the development one is a dev server to restart.
    for command in deployment_steps(backend=True, frontend=copied_frontend):
        console.print(f'  {command}', soft_wrap=True)
    console.print(
        f'[yellow]  The on_upgrade hook runs on that restart, from v'
        f'{meta["version"]}\'s own code, with old_version="{installed}".[/]'
    )
