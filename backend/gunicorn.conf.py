"""Gunicorn configuration — logging only.

Everything else (workers, binds, timeouts) stays on the command line so the
deployment knobs remain visible where they are set.

Gunicorn is the one process group that cannot be fixed from inside the app:
the arbiter boots, logs, and forks workers before any worker imports
``app.main``.  Pointing it at the same ``log_config.yaml`` the dev server uses
gives the whole stream one timestamp format.

``errorlog``/``accesslog`` are ``None`` because gunicorn's ``Logger.setup()``
attaches a handler of its own for each of them, *in addition* to whatever
``logconfig_dict`` installed — every line would print twice, once in
gunicorn's format and once in ours.  Access logging itself is unaffected:
``Logger.access()`` still emits because ``logconfig_dict`` is set, and the
record now travels through the root handler.
"""

from pathlib import Path

import yaml

logconfig_dict = yaml.safe_load((Path(__file__).parent / 'log_config.yaml').read_text())

errorlog = None
accesslog = None
