"""Backward-compatible shim — delegates to app.core.ssrf_guard."""

from app.core.ssrf_guard import *  # noqa: F403
from app.core.ssrf_guard import validate_webhook_url  # noqa: F401
