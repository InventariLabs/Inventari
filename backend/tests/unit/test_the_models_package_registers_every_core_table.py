"""``import app.models`` alone puts every core model in the metadata.

``migrations/env.py`` runs in a process of its own, where nothing else has
imported the services, so a model the package leaves out is a table
autogenerate offers to drop: ``ai_usage_logs`` was one. In the test process
the services have already imported every model, which is why this asks a
fresh interpreter.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_MODELS_DIR = Path(__file__).resolve().parents[2] / 'app' / 'models'
_TABLENAME = re.compile(r"^\s+__tablename__\s*=\s*['\"](\w+)['\"]", re.MULTILINE)


def test_every_core_table_is_registered_by_the_package():
    declared = {
        name
        for path in _MODELS_DIR.glob('*.py')
        for name in _TABLENAME.findall(path.read_text())
    }
    registered = subprocess.run(
        [
            sys.executable,
            '-c',
            'import app.models\n'
            'from app.database import Base\n'
            'print("\\n".join(Base.metadata.tables))',
        ],
        cwd=_MODELS_DIR.parents[1],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert declared - set(registered) == set()
