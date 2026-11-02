import sys

import typer
from rich.console import Console

arch_app = typer.Typer(no_args_is_help=True)
console = Console()


@arch_app.command()
def lint(
    baseline: str | None = typer.Option(
        None, help='Path to baseline file with accepted violations'
    ),
    write_baseline: bool = typer.Option(
        False, '--write-baseline', help='Write current violations as baseline and exit'
    ),
    quiet: bool = typer.Option(
        False,
        '--quiet',
        help='Collapse per-file L2 bypass notices into a single summary line',
    ),
    contracts_snapshot: str | None = typer.Option(
        None, help='Path to the committed contracts snapshot JSON'
    ),
    update_contracts_snapshot: bool = typer.Option(
        False,
        '--update-contracts-snapshot',
        help='Regenerate the contracts snapshot from current DTOs and exit',
    ),
    core_api_snapshot: str | None = typer.Option(
        None, help='Path to the committed core_api surface snapshot JSON'
    ),
    update_core_api_snapshot: bool = typer.Option(
        False,
        '--update-core-api-snapshot',
        help='Regenerate the core_api surface snapshot from the facade and exit',
    ),
    module_sdk_snapshot: str | None = typer.Option(
        None, help='Path to the committed module SDK snapshot JSON'
    ),
    update_module_sdk_snapshot: bool = typer.Option(
        False,
        '--update-module-sdk-snapshot',
        help=(
            'Regenerate the module SDK snapshot — exported names and hook '
            'signatures — and exit'
        ),
    ),
    write_rejection_ledger: bool = typer.Option(
        False,
        '--write-rejection-ledger',
        help=(
            'Regenerate the raw-ValueError-sentence ledger entries from the '
            'tree and exit (follow with --write-baseline-sizes)'
        ),
    ),
    write_baseline_sizes: bool = typer.Option(
        False,
        '--write-baseline-sizes',
        help=(
            'Record the current entry count of every suppression list and '
            'exit. The only way to change the ratchet.'
        ),
    ),
):
    """Check architecture boundaries (module imports, CQRS)."""
    from app.core.architecture_lint import main as arch_main

    # architecture_lint.main() uses argparse internally.
    # We override sys.argv to pass our CLI arguments through.
    argv = ['architecture_lint']
    if baseline:
        argv.extend(['--baseline', baseline])
    if write_baseline:
        argv.append('--write-baseline')
    if quiet:
        argv.append('--quiet')
    if contracts_snapshot:
        argv.extend(['--contracts-snapshot', contracts_snapshot])
    if update_contracts_snapshot:
        argv.append('--update-contracts-snapshot')
    if core_api_snapshot:
        argv.extend(['--core-api-snapshot', core_api_snapshot])
    if update_core_api_snapshot:
        argv.append('--update-core-api-snapshot')
    if module_sdk_snapshot:
        argv.extend(['--module-sdk-snapshot', module_sdk_snapshot])
    if update_module_sdk_snapshot:
        argv.append('--update-module-sdk-snapshot')
    if write_rejection_ledger:
        argv.append('--write-rejection-ledger')
    if write_baseline_sizes:
        argv.append('--write-baseline-sizes')

    original_argv = sys.argv
    sys.argv = argv
    try:
        exit_code = arch_main()
    finally:
        sys.argv = original_argv

    raise typer.Exit(code=exit_code)
