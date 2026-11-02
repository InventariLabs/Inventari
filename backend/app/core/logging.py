"""
Centralised logging helpers.

Goal: every module should obtain its logger via ``get_logger(__name__)``
instead of calling ``logging.info(...)`` directly.  This:

- Lets us swap the underlying handler/format without touching call sites
- Gives every module a logger named after its dotted import path
  (e.g. ``app.modules.recipes.services.picking``), which is what
  ``logging.basicConfig`` already supports via ``%(name)s``
- Avoids the pitfall of bare ``logging.info`` calls, which write to the
  *root* logger and are hard to silence or filter per-module

Two handlers are configured, both with the SAME format:

1. **StreamHandler** (stdout) — what ``docker compose logs backend`` shows
2. **RotatingFileHandler** (``LOG_DIR/app.log``) — rotates at 10 MB with 5
   backups (max ~50 MB on disk)

The console used to run a shorter format without ``%(asctime)s``, so the
stream people actually read had no clock on it and no line could be tied to
an incident.  One format now serves both, and the timestamp is ISO-8601 in
**UTC** — containers run UTC anyway, and an explicit ``Z`` is what log
aggregators parse without guessing a local zone.

Servers log through this configuration too.  Uvicorn and gunicorn install
their own handlers with ``propagate = False``, so their lines (``Application
startup complete.``) would otherwise bypass everything here; see
:func:`adopt_server_loggers`.  Processes that never import the app — the
``--reload`` supervisor, the gunicorn arbiter — are covered instead by
``backend/log_config.yaml``, which builds its formatter from
:func:`build_formatter` so there is still only one format string.

Usage::

    # module top
    from app.core.logging import get_logger
    logger = get_logger(__name__)

    def do_thing():
        logger.info('did thing')
        try:
            ...
        except (OSError, ValueError):
            logger.exception('boom')
"""

from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

LOG_FORMAT: Final[str] = (
    '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] %(message)s'
)
TIME_FORMAT: Final[str] = '%Y-%m-%dT%H:%M:%S'
_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT: Final[int] = 5

_NOISY_LOGGERS: Final[tuple[str, ...]] = (
    'uvicorn.access',
    'sqlalchemy.engine',
    'sqlalchemy.pool',
    'watchfiles',
)

#: Loggers the servers configure behind our back.  Uvicorn applies its own
#: ``dictConfig`` before importing the app and gunicorn attaches handlers in
#: the arbiter before forking; both set ``propagate = False``, so their records
#: never reach the root handlers configured here.
_SERVER_LOGGERS: Final[tuple[str, ...]] = (
    'uvicorn',
    'uvicorn.error',
    'uvicorn.access',
    'gunicorn',
    'gunicorn.error',
    'gunicorn.access',
)


class RequestIdFilter(logging.Filter):
    """Inject ``request_id`` into every log record from the contextvar.

    When no request is in flight, defaults to ``'-'`` so the format
    string always finds the attribute.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from app.core._request_id import get_request_id

        record.request_id = get_request_id() or '-'
        return True


class UtcFormatter(logging.Formatter):
    """ISO-8601 timestamps in UTC, with milliseconds and an explicit ``Z``.

    ``logging.Formatter`` renders local time with a comma before the
    milliseconds (``2026-08-15 10:22:31,482``), which is neither ISO-8601 nor
    unambiguous across hosts in different zones.
    """

    converter = staticmethod(time.gmtime)

    def formatTime(  # noqa: N802 - stdlib logging spells it this way
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        stamp = time.strftime(datefmt or TIME_FORMAT, self.converter(record.created))
        return f'{stamp}.{int(record.msecs):03d}Z'


def build_formatter() -> logging.Formatter:
    """The one formatter every handler and every server process uses.

    Referenced as a ``()`` factory from ``backend/log_config.yaml`` so the
    server configs cannot drift away from the format used here.
    """
    return UtcFormatter(LOG_FORMAT)


def adopt_server_loggers() -> None:
    """Route uvicorn/gunicorn records through the root handlers.

    Their own handlers are dropped rather than reformatted: leaving them in
    place next to a propagating logger prints every line twice.
    """
    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        for handler in list(server_logger.handlers):
            server_logger.removeHandler(handler)
        server_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger named after the caller.

    The returned object is a stdlib ``logging.Logger`` — call
    ``.info()``, ``.warning()``, ``.error()``, etc. as usual.

    Idempotent: calling ``get_logger('foo')`` twice returns the same
    logger instance (logging.getLogger is already cached internally).
    """
    return logging.getLogger(name)


def configure_logging(level: int | None = None, log_dir: str | None = None) -> None:
    """Idempotent logging configuration.

    Parameters
    ----------
    level:
        Logging level.  When *None*, reads ``LOG_LEVEL`` from settings
        (via environment) or falls back to ``logging.INFO``.
    log_dir:
        Directory for the rotating log file.  When *None*, reads
        ``LOG_DIR`` from settings (via environment) or falls back to
        ``/app/logs``.  The directory is created automatically.

    The file handler is skipped when:

    - ``TESTING=true`` (tests don't need persistent log files; the console
      handler is enough for debugging)
    - the log directory cannot be created (e.g. CI runs against a
      read-only checkout where ``/app/logs`` is not writable)

    Safe to call multiple times — handlers are reset on each call so we
    don't duplicate log lines when the app reloads (e.g. in tests).
    """
    if level is None:
        level = _resolve_level()
    if log_dir is None:
        log_dir = os.getenv('LOG_DIR', '/app/logs')

    testing = os.getenv('TESTING', '').lower() == 'true'

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(build_formatter())
    console_handler.addFilter(RequestIdFilter())
    root.addHandler(console_handler)

    adopt_server_loggers()

    if testing:
        # Tests use the console handler only — no persistent log file.
        for logger_name in _NOISY_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        return

    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as exc:
        # Read-only checkout (e.g. CI) or sandboxed process — fall back
        # to console-only logging rather than failing the import.
        logging.getLogger(__name__).warning(
            'Could not create log directory %s (%s) — file logging disabled',
            log_path,
            exc,
        )
        for logger_name in _NOISY_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        return

    file_handler = RotatingFileHandler(
        log_path / 'app.log',
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding='utf-8',
    )
    file_handler.setFormatter(build_formatter())
    file_handler.addFilter(RequestIdFilter())
    root.addHandler(file_handler)

    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _resolve_level() -> int:
    raw = os.getenv('LOG_LEVEL', 'INFO').upper()
    return getattr(logging, raw, logging.INFO)


__all__ = [
    'adopt_server_loggers',
    'build_formatter',
    'configure_logging',
    'get_logger',
]
