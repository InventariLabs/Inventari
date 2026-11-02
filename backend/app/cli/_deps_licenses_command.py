"""`manage.py audit scan-dependencies` — the licence gate for what we install."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ._deps_licenses import (
    Dependency,
    ScanResult,
    collect_backend,
    collect_frontend,
)
from ._deps_licenses_report import (
    ASSET_COMPONENTS,
    IMAGE_COMPONENTS,
    SYSTEM_COMPONENTS,
    render_markdown,
    summarize,
)

console = Console()


def _print_group(title: str, deps: list[Dependency], style: str) -> None:
    if not deps:
        return
    table = Table(
        'Package',
        'Version',
        'Licence',
        'Declared as',
        'Where',
        'Why',
        title=title,
        title_style=style,
    )
    for dep in sorted(deps, key=lambda d: (d.ecosystem, d.name.lower())):
        # The raw string matters here: deciding on a package means seeing what
        # its metadata actually claimed, not only what we concluded.
        declared = '' if dep.raw.strip() == dep.licence else dep.raw
        table.add_row(
            dep.name,
            dep.version,
            dep.licence,
            declared,
            dep.ecosystem,
            dep.note or '',
        )
    console.print(table)


def scan_dependencies(
    backend_dir: Annotated[
        Path,
        typer.Option('--backend-dir', help='Directory holding pyproject.toml/uv.lock'),
    ] = Path('.'),
    frontend_dir: Annotated[
        Path,
        typer.Option(
            '--frontend-dir', help='Directory holding the frontend package.json'
        ),
    ] = Path('../frontend'),
    write: Annotated[
        bool,
        typer.Option('--write', help='Regenerate THIRD_PARTY_LICENSES.md'),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(
            '--output',
            help='Where --write puts the inventory '
            '(default: THIRD_PARTY_LICENSES.md next to the backend directory)',
        ),
    ] = None,
    skip_frontend: Annotated[
        bool,
        typer.Option('--skip-frontend', help='Backend only (no node_modules present)'),
    ] = False,
) -> None:
    """Check the licence of every dependency that ships, and list them all.

    This reads what the manifests actually resolve to — the blind spot that
    let a GPL package sit in the runtime set unnoticed.

    Exit code 1 when something on the blocking list is installed. Licences
    needing a human decision (LGPL, CC-BY, anything unrecognised) are reported
    as warnings and do not fail the build.
    """
    result = ScanResult()

    console.print('[bold cyan]Backend runtime[/bold cyan] — reading installed metadata')
    try:
        result.dependencies.extend(collect_backend(backend_dir.resolve()))
    except RuntimeError as exc:
        console.print(f'[red]Error:[/red] backend scan failed: {exc}')
        raise typer.Exit(1) from exc

    if skip_frontend:
        console.print('[dim]Frontend skipped (--skip-frontend).[/dim]')
    else:
        console.print('[bold cyan]Frontend production tree[/bold cyan] — npm ls')
        try:
            result.dependencies.extend(collect_frontend(frontend_dir.resolve()))
        except RuntimeError as exc:
            console.print(f'[red]Error:[/red] frontend scan failed: {exc}')
            raise typer.Exit(1) from exc

    result.dependencies.extend(SYSTEM_COMPONENTS)
    result.dependencies.extend(IMAGE_COMPONENTS)
    result.dependencies.extend(ASSET_COMPONENTS)

    stats = summarize(result)
    console.print('\n[bold]Dependency Licence Gate[/bold]')
    console.print(f'  Components checked:  {stats["total"]}')
    console.print(f'  Permissive:          {stats["allowed"]}')
    console.print(f'  Needs a decision:    {stats["review"]}')
    console.print(f'  [bold]Blocking:            {stats["blocked"]}[/bold]\n')

    _print_group('Needs a decision', result.by_verdict('review'), 'yellow')
    _print_group('Blocking', result.by_verdict('blocked'), 'red')

    if write:
        # Anchored to the backend directory, not the caller's cwd — otherwise
        # the file lands wherever the command happened to be invoked from.
        target = (
            output.resolve()
            if output
            else backend_dir.resolve().parent / 'THIRD_PARTY_LICENSES.md'
        )
        target.write_text(render_markdown(result), encoding='utf-8')
        console.print(f'[green]Wrote[/green] {target}')

    if stats['blocked']:
        console.print(
            '\n[red bold]✗ BLOCKED[/red bold] — a dependency is licensed in a way '
            'that a commercial release cannot carry. Replace it, or add a '
            'reasoned entry to EXCEPTIONS if the metadata is simply wrong.'
        )
        raise typer.Exit(1)

    console.print('[green bold]✓ CLEAN — nothing blocking.[/green bold]')
