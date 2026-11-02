from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine

from app.core.logging import get_logger

# Context variable to store query count and total time per request
db_query_stats: ContextVar[dict[str, Any] | None] = ContextVar(
    'db_query_stats', default=None
)

logger = get_logger(__name__)


@event.listens_for(Engine, 'before_cursor_execute')
def before_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    """Triggers before each query execution."""
    context._query_start_time = time.time()


@event.listens_for(Engine, 'after_cursor_execute')
def after_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    """Triggers after each query execution. Calculates duration."""
    duration = time.time() - context._query_start_time
    try:
        stats = db_query_stats.get() or {'count': 0, 'total_time': 0.0}
        stats['count'] += 1
        stats['total_time'] += duration
        db_query_stats.set(stats)
    except (LookupError, AttributeError) as exc:
        logger.warning('Failed to update query stats: %s', exc)


def get_performance_stats() -> tuple[int, float]:
    """Retrieve current request's performance stats (count, total_time)."""
    stats = db_query_stats.get() or {'count': 0, 'total_time': 0.0}
    return stats['count'], stats['total_time']


def reset_query_count() -> None:
    """Reset counter for a new request."""
    db_query_stats.set({'count': 0, 'total_time': 0.0})
