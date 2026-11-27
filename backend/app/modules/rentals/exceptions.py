"""Refusals that carry the rows the screen needs to offer a way out."""

from __future__ import annotations

from typing import Any


class RentalConflictError(ValueError):
    """A 409 with structured details: what is in the way, and where to go.

    Routers catch it and answer ``ConflictException``; services raise it the
    way they raise ``ValueError``, so no HTTP type enters the service layer.
    """

    def __init__(
        self,
        key: str,
        *,
        code: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.key = key
        self.code = code
        self.details = details or {}
        self.kwargs = kwargs
        super().__init__(key)
