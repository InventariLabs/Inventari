"""Stored secrets: rewrite them under the current encryption key.

Every secret an organization saves — the SMTP password, AI connection keys,
module settings marked ``format: secret``, webhook signing secrets — is sealed
with a key derived from ``ENCRYPTION_KEY`` (``SECRET_KEY`` on an install that
never set one) and ``FERNET_SALT``. Changing that key leaves every stored value
sealed under the old one. The read path keeps opening them while the old key is
``PREVIOUS_ENCRYPTION_KEY`` or ``SECRET_KEY``; this command rewrites them under
the current key, after which the old one can be dropped. DEPLOYMENT.md, "Rotating
the encryption key", has the order of the steps.
"""

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import bootstrap_db, console

secrets_app = typer.Typer(no_args_is_help=True)


@dataclass
class ReencryptReport:
    rewritten: int = 0
    #: Where each value no known key opens sits; those stay stored as they are.
    unreadable: list[str] = field(default_factory=list)


def _rewrite(
    current: object,
    rewrap: Callable[[str], str | None],
    where: str,
    report: ReencryptReport,
) -> str | None:
    """The new stored text for *current*, or ``None`` to leave it alone."""
    from app.services.crypto_service import UndecryptableSecretError

    if not isinstance(current, str) or not current:
        return None
    try:
        new = rewrap(current)
    except (UndecryptableSecretError, PermissionError):
        # Rewriting it would store an empty secret over one the right key
        # might still open.
        report.unreadable.append(where)
        return None
    if new is not None:
        report.rewritten += 1
    return new


def _rewrite_leaf(
    values: dict,
    path: tuple[str, ...],
    rewrap: Callable[[str], str | None],
    where: str,
    report: ReencryptReport,
) -> bool:
    parent: object = values
    for segment in path[:-1]:
        parent = parent.get(segment) if isinstance(parent, dict) else None
    if not isinstance(parent, dict):
        return False
    new = _rewrite(parent.get(path[-1]), rewrap, where, report)
    if new is None:
        return False
    parent[path[-1]] = new
    return True


def _module_settings_paths(module_name: str) -> list[tuple[str, ...]]:
    from app.core.module_registry import module_registry
    from app.core.settings_validator import iter_secret_paths

    module = module_registry.get(module_name)
    schema = module.get_settings_schema() if module else None
    return list(iter_secret_paths(schema)) if schema else []


def _organization_settings(db: Session, report: ReencryptReport) -> None:
    from app.models.organization import Organization
    from app.services.crypto_service import (
        SENSITIVE_PATHS,
        reencrypt_app_secret,
        reencrypt_module_secret,
    )

    for org in db.scalars(select(Organization)):
        values = copy.deepcopy(org.settings or {})
        changed = False
        for path in SENSITIVE_PATHS:
            where = f'{org.name}: settings {".".join(path)}'
            changed |= _rewrite_leaf(values, path, reencrypt_app_secret, where, report)
        for namespace, branch in values.items():
            if not namespace.startswith('module:') or not isinstance(branch, dict):
                continue
            module_name = namespace.split(':', 1)[1]
            rewrap = partial(reencrypt_module_secret, module_name)
            for path in _module_settings_paths(module_name):
                where = f'{org.name}: settings {namespace}.{".".join(path)}'
                changed |= _rewrite_leaf(branch, path, rewrap, where, report)
        if changed:
            org.settings = values


def _column(
    db: Session,
    column,
    rewrap: Callable[[str], str | None],
    report: ReencryptReport,
) -> None:
    model = column.class_
    rows = db.scalars(select(model).where(column.is_not(None), column != ''))
    for row in rows:
        where = f'{model.__tablename__}.{column.key} {row.id}'
        new = _rewrite(getattr(row, column.key), rewrap, where, report)
        if new is not None:
            setattr(row, column.key, new)


def reencrypt_secrets_impl(db: Session) -> ReencryptReport:
    """Rewrite in *db* every stored secret the current key does not open.

    Commits nothing: the caller commits to apply, or closes the session for a
    dry run. Idempotent — a value already under the current key is left alone.
    """
    from app.core.module_registry import module_registry
    from app.models.ai_connection import AiConnection
    from app.models.email_job import EmailJob
    from app.services.crypto_service import (
        reencrypt_app_secret,
        reencrypt_module_secret,
    )

    report = ReencryptReport()
    _organization_settings(db, report)
    for column in (
        AiConnection.api_key_enc,
        EmailJob.smtp_config_enc,
        EmailJob.failure_notice_enc,
    ):
        _column(db, column, reencrypt_app_secret, report)
    for module in module_registry.get_all():
        rewrap = partial(reencrypt_module_secret, module.metadata.name)
        for column in module.get_secret_columns():
            _column(db, column, rewrap, report)
    return report


@secrets_app.command('reencrypt')
def reencrypt_secrets(
    dry_run: bool = typer.Option(
        True,
        '--dry-run/--apply',
        help='Default --dry-run. Pass --apply to write the re-encrypted values.',
    ),
) -> None:
    """Re-encrypt every stored secret under the current encryption key.

    Run it after changing ENCRYPTION_KEY (or SECRET_KEY on an install without
    one), with the old key in PREVIOUS_ENCRYPTION_KEY. Walks organization
    settings, module settings, AI connections, queued mail and every secret
    column a module declares. A value no known key opens is reported and left
    as it is; exit code 1 says there was one.
    """
    bootstrap_db()

    from app.database import SessionLocal

    with SessionLocal() as db:
        report = reencrypt_secrets_impl(db)
        if not dry_run:
            db.commit()

    verb = 'would re-encrypt' if dry_run else 're-encrypted'
    console.print(f'[green]{verb} {report.rewritten} secret(s).[/]')
    for where in report.unreadable:
        console.print(f'  [yellow]⚠ no known key opens it, left as it is: {where}[/]')
    if dry_run:
        console.print('[yellow]Dry run — pass --apply to write.[/]')
    if report.unreadable:
        raise typer.Exit(code=1)
