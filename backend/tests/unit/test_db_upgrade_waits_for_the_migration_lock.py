"""``db upgrade`` migrates under the same lock the backend's entrypoint holds.

On a machine with no images the bootstrap starts the containers and runs
``db upgrade`` in the backend at the moment the entrypoint begins its own
migration of the same empty database. Without the lock the two ran the module
chains side by side, one lost with a ``UniqueViolation`` on a version table,
and the container exited and restarted under the bootstrap's next command.
The command now queues behind whoever is migrating, and the entrypoint's pass
after it finds nothing left to do.
"""

from __future__ import annotations

import contextlib

from app.cli import commands_db


def test_the_whole_upgrade_runs_inside_the_migration_lock(monkeypatch) -> None:
    order: list[str] = []

    @contextlib.contextmanager
    def _lock():
        order.append('lock')
        yield
        order.append('unlock')

    monkeypatch.setattr(commands_db, 'hold_migration_lock', _lock)
    monkeypatch.setattr(
        'alembic.command.upgrade', lambda cfg, rev: order.append(f'core:{rev}')
    )
    monkeypatch.setattr(
        commands_db, '_upgrade_all_modules', lambda: order.append('modules')
    )

    commands_db.upgrade('head')

    assert order == ['lock', 'core:head', 'modules', 'unlock']
