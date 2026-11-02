"""Shared SQL helpers for claim-then-work queue tables.

Both ``_webhook_workers`` and ``email_jobs`` claim rows that are either
(a) due for (re)processing or (b) zombies left by a crashed worker. The
OR-clause shape is identical — keep it in one place.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement


def due_or_zombie_clause(
    *,
    status_col: Any,
    pending_status: str,
    inflight_status: str,
    due_at_col: Any,
    claimed_col: Any,
    now: datetime,
    zombie_cutoff: Any,
) -> ColumnElement[bool]:
    """Build ``(status=pending AND due_at<=now) OR (status=inflight AND claimed<cutoff)``.

    ``zombie_cutoff`` may be a plain datetime (flat threshold) or a SQL
    expression (per-row threshold, e.g. derived from a joined timeout
    column).
    """
    return or_(
        and_(status_col == pending_status, due_at_col <= now),
        and_(status_col == inflight_status, claimed_col < zombie_cutoff),
    )
