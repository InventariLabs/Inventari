"""Module-safe access to the periodic task scheduler.

Modules register their background workers here instead of importing
``app.core.scheduler.task_scheduler`` directly.

Org scoping: scheduled tasks are process-global (module-scoped), NOT
per-organization. Handlers that touch tenant data must iterate the
relevant organizations themselves (e.g. via ``context.global_session()``)
and filter by ``organization_id`` inside the handler.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.core.module_identity import refuse_foreign_module


class CoreSchedulerAPI:
    """Public Core API for periodic task registration."""

    def register_task(
        self,
        name: str,
        interval: timedelta,
        handler: Callable[[], Any],
        *,
        module_name: str,
        is_persistent: bool = False,
    ) -> None:
        """Register a periodic task under ``<module_name>.<name>``.

        ``is_persistent=True`` tasks go through Redis Streams (guaranteed
        execution, survive restart); local tasks are in-memory only.

        Raises ``PermissionError`` when the caller is a module naming a
        different module's namespace (``app.core.module_identity``): a task
        key is a module-scoped name, so registering under another module's
        name would hand your job to its disable hook.
        """
        refuse_foreign_module(module_name, api='core_api.scheduler.register_task')
        from app.core.scheduler import task_scheduler

        task_scheduler.register(
            name=name,
            interval=interval,
            handler=handler,
            module_name=module_name,
            is_persistent=is_persistent,
        )

    def unregister_task(self, name: str, *, module_name: str) -> bool:
        """Unregister a periodic task. Returns True when the task existed.

        Raises ``PermissionError`` when the caller is a module naming a
        different module's namespace (``app.core.module_identity``):
        unhooking another module's job with a copied name was the accident
        this refusal exists for.
        """
        refuse_foreign_module(module_name, api='core_api.scheduler.unregister_task')
        from app.core.scheduler import task_scheduler

        return task_scheduler.unregister(name, module_name)
