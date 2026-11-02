"""Audit CLI commands — licence gate on the dependencies we install."""

import typer

from ._deps_licenses_command import scan_dependencies

audit_app = typer.Typer(no_args_is_help=True)
audit_app.command('scan-dependencies')(scan_dependencies)

__all__ = ['audit_app', 'scan_dependencies']
