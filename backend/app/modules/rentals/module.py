from app.core.module_sdk import ModuleContext, define_module
from app.core.public_api import core_api

from ._reminders import CHECK_INTERVAL, run_rental_reminder_check_async
from .router import router


async def _run_reminder_pass(context: ModuleContext) -> None:
    """One scheduled pass; the job owns its session and its commit."""
    async with context.global_session() as db:
        await run_rental_reminder_check_async(db)
        await db.commit()


def _start_reminder_worker(context: ModuleContext) -> None:
    """Register the reminder pass with a session of the module's own.

    The scheduler is process-wide, so the handler opens its session through
    the module context and iterates the organizations itself.
    """
    core_api.scheduler.register_task(
        'rental_reminders',
        CHECK_INTERVAL,
        lambda: _run_reminder_pass(context),
        module_name='rentals',
    )


module = define_module(router=router, on_startup_hook=_start_reminder_worker)
