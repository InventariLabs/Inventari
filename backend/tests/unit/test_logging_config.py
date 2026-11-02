"""Every line on stdout carries a timestamp, and one format serves them all.

The console handler used to run ``%(levelname)s - %(name)s - %(message)s``,
so ``docker compose logs backend`` — the stream people actually read — had no
clock on it.  ``app.log`` had one, in a different format, and uvicorn printed
in a third.  These tests pin the three halves of the fix: the format itself,
the servers adopting it, and the launch commands still passing the config.
"""

import logging
import logging.config
import time
from pathlib import Path

import pytest
import yaml

from app.core.logging import (
    LOG_FORMAT,
    UtcFormatter,
    adopt_server_loggers,
    build_formatter,
    configure_logging,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOG_CONFIG = BACKEND_ROOT / 'log_config.yaml'


@pytest.fixture(autouse=True)
def _restore_logging():
    """Give each test the global logging state back."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_servers = {}
    for name in ('uvicorn', 'uvicorn.error', 'gunicorn.error'):
        server = logging.getLogger(name)
        saved_servers[name] = (list(server.handlers), server.propagate)
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for name, (handlers, propagate) in saved_servers.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.propagate = propagate


def _record(**overrides) -> logging.LogRecord:
    record = logging.LogRecord(
        name='app.middleware',
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='"GET /health" 200',
        args=(),
        exc_info=None,
    )
    record.request_id = '-'
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


class TestFormat:
    def test_console_line_starts_with_an_iso_utc_timestamp(self):
        configure_logging(level=logging.INFO)

        (console,) = logging.getLogger().handlers
        line = console.format(_record(created=0.0, msecs=482.0))

        assert line.startswith('1970-01-01T00:00:00.482Z - app.middleware - INFO')

    def test_timestamp_is_utc_even_where_the_host_is_not(self, monkeypatch):
        # The old formatter rendered localtime; on a Warsaw host that is an
        # hour off UTC in winter and two in summer, so aggregated logs from
        # two machines could not be ordered against each other.
        monkeypatch.setenv('TZ', 'Europe/Warsaw')
        time.tzset()
        try:
            line = build_formatter().format(_record(created=0.0, msecs=0.0))
        finally:
            monkeypatch.undo()
            time.tzset()

        assert line.startswith('1970-01-01T00:00:00.000Z')

    def test_stdout_carries_the_request_id(self):
        configure_logging(level=logging.INFO)

        (console,) = logging.getLogger().handlers
        line = console.format(_record(request_id='c0ffee'))

        assert '[c0ffee]' in line

    def test_console_and_file_share_one_format(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TESTING', 'false')

        configure_logging(level=logging.INFO, log_dir=str(tmp_path))

        formats = {h.formatter._fmt for h in logging.getLogger().handlers}
        assert len(logging.getLogger().handlers) == 2
        assert formats == {LOG_FORMAT}


class TestServerLoggers:
    def test_uvicorn_lines_reach_the_root_handlers(self):
        # What uvicorn does to itself before the app is imported.
        uvicorn_error = logging.getLogger('uvicorn.error')
        uvicorn_error.addHandler(logging.StreamHandler())
        uvicorn_error.propagate = False

        configure_logging(level=logging.INFO)

        assert uvicorn_error.handlers == []
        assert uvicorn_error.propagate is True

    def test_gunicorn_handlers_are_dropped_not_kept_alongside(self):
        # Leaving gunicorn's handler in place next to a propagating logger
        # prints every arbiter line twice, once in each format.
        gunicorn_error = logging.getLogger('gunicorn.error')
        gunicorn_error.addHandler(logging.StreamHandler())
        gunicorn_error.propagate = False

        adopt_server_loggers()

        assert gunicorn_error.handlers == []
        assert gunicorn_error.propagate is True


class TestServerConfigFile:
    def test_yaml_builds_the_same_formatter_the_app_uses(self):
        logging.config.dictConfig(yaml.safe_load(LOG_CONFIG.read_text()))

        (console,) = logging.getLogger().handlers
        assert isinstance(console.formatter, UtcFormatter)
        assert console.formatter._fmt == LOG_FORMAT

    @pytest.mark.parametrize('name', ['gunicorn.error', 'gunicorn.access'])
    def test_yaml_gives_gunicorn_loggers_a_handler_of_the_shared_kind(self, name):
        # gunicorn.glogging.Logger.__init__ sets propagate = False on both
        # loggers before this config is applied, and gunicorn.conf.py disables
        # the handlers gunicorn would otherwise attach. Leaving these entries
        # out (or letting them propagate) makes the arbiter silent — verified
        # by running gunicorn with an empty `loggers` block: no output at all.
        config = yaml.safe_load(LOG_CONFIG.read_text())

        assert config['loggers'][name]['handlers'] == ['console']
        assert config['loggers'][name]['propagate'] is False

    def test_the_image_still_starts_gunicorn_with_the_config(self):
        # Drop the flag and the server silently falls back to its own format —
        # nothing fails, the timestamps just go away again.  Only files under
        # backend/ are checked: the test container mounts that directory alone,
        # so the compose files at the repo root are out of reach from here.
        assert '--config gunicorn.conf.py' in (BACKEND_ROOT / 'Dockerfile').read_text()

    def test_gunicorn_config_hands_the_streams_to_the_dict_config(self):
        # errorlog/accesslog left at their gunicorn defaults would attach a
        # second handler per stream and double every arbiter line.
        source = (BACKEND_ROOT / 'gunicorn.conf.py').read_text()

        assert 'errorlog = None' in source
        assert 'accesslog = None' in source
