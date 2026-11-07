"""Per-module migration runner.

Runs Alembic migrations for a single module using a separate version table
(``alembic_version_<module>``), completely independent of core migrations.

Usage::

    from app.core.module_migrations import run_module_migrations

    # Upgrade a module to head
    run_module_migrations("api_keys", "upgrade")

    # Downgrade a module to base
    run_module_migrations("api_keys", "downgrade")

    # Stamp without running
    run_module_migrations("api_keys", "stamp", revision="head")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config

from app.core.operator_error import OperatorError

logger = logging.getLogger(__name__)

MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def module_migrations_dir(module_name: str) -> Path:
    """Return the migrations directory for a module, or raise if missing."""
    migrations_dir = MODULES_ROOT / module_name / 'migrations'
    if not migrations_dir.exists():
        raise FileNotFoundError(
            f"Module '{module_name}' has no migrations directory at {migrations_dir}. "
            f"Run 'module create' to scaffold one."
        )
    return migrations_dir


def discover_modules_with_migrations(modules_root: Path | None = None) -> list[str]:
    """Return sorted names of modules that own a non-empty ``migrations/versions/``.

    One definition shared by the migration runner, the doctor and the CLI, so a
    module cannot be visible to one and invisible to another.
    """
    root = modules_root if modules_root is not None else MODULES_ROOT
    if not root.is_dir():
        return []
    return sorted(
        module_dir.name
        for module_dir in root.iterdir()
        if module_dir.is_dir()
        and not module_dir.name.startswith('_')
        and any(
            py_file.name != '__init__.py'
            for py_file in (module_dir / 'migrations' / 'versions').glob('*.py')
        )
    )


def _build_alembic_config(module_name: str, db_url: str) -> Config:
    """Build an Alembic Config pointing at the module's migrations dir."""
    migrations_dir = module_migrations_dir(module_name)

    cfg = Config()
    cfg.set_main_option('script_location', str(migrations_dir))
    # The option is read back through configparser, which takes ``%`` for
    # interpolation: a password with a URL-encoded character in it
    # (``%24`` for ``$``) made every module's chain refuse to start.
    cfg.set_main_option('sqlalchemy.url', db_url.replace('%', '%%'))
    # The env.py handles version_table via context.configure
    return cfg


def get_version_table_name(module_name: str) -> str:
    """Return the Alembic version table name for a module."""
    return f'alembic_version_{module_name}'


def run_module_migrations(
    module_name: str,
    action: Literal['upgrade', 'downgrade', 'stamp', 'current'],
    db_url: str | None = None,
    revision: str = 'head',
) -> None:
    """Run a migration action for a single module.

    Parameters
    ----------
    module_name:
        The module name (e.g. ``"api_keys"``).
    action:
        ``"upgrade"`` — run upgrade to *revision* (default ``"head"``).
        ``"downgrade"`` — run downgrade to *revision* (default ``"base"``).
        ``"stamp"`` — stamp the version table to *revision* without running.
        ``"current"`` — print current revision.
    db_url:
        Database URL. If ``None``, reads from ``DATABASE_URL`` env var.
    revision:
        Target revision for upgrade/downgrade/stamp. Defaults to ``"head"``
        for upgrade and ``"base"`` for downgrade.
    """
    import os

    if db_url is None:
        db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise RuntimeError('DATABASE_URL not set and no db_url provided')

    cfg = _build_alembic_config(module_name, db_url)

    if action == 'upgrade':
        logger.info("Upgrading module '%s' to %s", module_name, revision)
        command.upgrade(cfg, revision)
    elif action == 'downgrade':
        target = revision if revision != 'head' else 'base'
        logger.info("Downgrading module '%s' to %s", module_name, target)
        command.downgrade(cfg, target)
    elif action == 'stamp':
        logger.info("Stamping module '%s' at %s", module_name, revision)
        command.stamp(cfg, revision)
    elif action == 'current':
        command.current(cfg)
    else:
        raise OperatorError(f'Unknown action: {action}')
