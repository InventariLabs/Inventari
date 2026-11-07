import typer

from app.cli.commands_arch import arch_app
from app.cli.commands_audit import audit_app
from app.cli.commands_backfill import backfill_app
from app.cli.commands_db import db_app
from app.cli.commands_demo import demo_app
from app.cli.commands_module import module_app
from app.cli.commands_qa import qa_app
from app.cli.commands_secrets import secrets_app
from app.cli.commands_shell import shell_command
from app.cli.commands_user import user_app

app = typer.Typer(
    help='Inventari CLI - Administration and Development tool',
    no_args_is_help=True,
    add_completion=False,
)

# Sub-Typers (command groups)
app.add_typer(db_app, name='db', help='Database management (reset, seed, migrate)')
app.add_typer(user_app, name='user', help='User management (create-admin, erase)')
app.add_typer(
    demo_app, name='demo', help='Demo instance (reset — destructive, demo only)'
)
app.add_typer(
    module_app, name='module', help='Module management (create, validate, list)'
)
app.add_typer(arch_app, name='arch', help='Architecture tools (lint)')
app.add_typer(audit_app, name='audit', help='Audit tools (dependency licences)')
app.add_typer(backfill_app, name='backfill', help='One-shot data backfills')
app.add_typer(
    secrets_app, name='secrets', help='Stored secrets (re-encrypt after a key rotation)'
)
app.add_typer(qa_app, name='qa', help='QA fixtures (development and staging only)')

# Top-level commands
app.command(name='shell')(shell_command)


# Plugin CLI — discovery after loading modules
def _register_module_cli_plugins():
    """Register CLI plugins from trusted modules."""
    try:
        from app.core.module_registry import module_registry

        module_registry.discover_modules()

        for module in module_registry.get_all():
            if not module.metadata.is_trusted:
                continue
            if hasattr(module, 'cli_app') and isinstance(module.cli_app, typer.Typer):
                app.add_typer(
                    module.cli_app,
                    name=module.metadata.name,
                    help=f'Commands for {module.metadata.display_name} module',
                )
    except Exception:  # noqa: BLE001 — discovery may fail without a DB; core commands still work
        # Module discovery may fail if DB is not available;
        # core CLI commands should still work.
        pass


_register_module_cli_plugins()

if __name__ == '__main__':
    app()
