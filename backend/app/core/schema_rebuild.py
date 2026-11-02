"""Who may rewrite the schema, and how a background job learns it is happening.

A demo rebuild drops the schema and builds it again while the backend that
serves the demo keeps running. Its periodic jobs (the outbox relay, the email
queue, the delivery retries) went on ticking against whatever the database
looked like at that moment, and each tick that landed between the drop and
the last migration logged a missing table or column.

The rebuild already holds an advisory lock for its whole destructive part, so
that a backend starting beside it does not migrate into a half-dropped schema
(``app.cli._migration_lock``). A job can ask the same lock instead of
inventing a second signal that could disagree with it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

#: Arbitrary constant shared by every process that may rewrite the schema:
#: migration-running backends and a database rebuild.
MIGRATION_LOCK_KEY = 727301


@asynccontextmanager
async def schema_held_steady() -> AsyncIterator[bool]:
    """Hold the schema still for the length of a job, or say it is being rewritten.

    Yields ``True`` when the job may run: it holds a shared claim on the key
    until the block ends, so a rebuild asking for the key exclusively waits for
    the job to finish instead of dropping tables under it. Yields ``False``
    when a rebuild or a migration holds (or waits for) the key, and the job
    should not start.

    The claim is ``pg_try_advisory_xact_lock_shared`` on a session whose
    transaction stays open for the block and is rolled back after it, so the
    database releases it with the transaction — through a pooler, and even if
    the connection dies. A probe that cannot reach the database says "go": the
    job that follows will fail on its own, loudly, as it did before.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.database import AsyncSessionLocal

    db = AsyncSessionLocal()  # type: ignore[misc]
    try:
        granted = await db.scalar(
            text('SELECT pg_try_advisory_xact_lock_shared(:key)'),
            {'key': MIGRATION_LOCK_KEY},
        )
    except (SQLAlchemyError, OSError):
        granted = True
    try:
        yield bool(granted)
    finally:
        await db.close()
