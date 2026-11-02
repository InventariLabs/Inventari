"""Request ID context variable for correlation across logs and responses."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

# Set by RequestIDMiddleware at the start of each request.
request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)


def generate_request_id() -> str:
    """Generate a new request ID (UUID4 hex)."""
    return uuid4().hex


def get_request_id() -> str | None:
    """Return the current request ID, or None if outside a request."""
    return request_id_var.get()
