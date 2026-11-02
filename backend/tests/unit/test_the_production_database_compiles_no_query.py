"""The production database answers without compiling each statement first.

PostgreSQL turns a statement into machine code (JIT) once its estimated cost
passes ``jit_above_cost``, and over an organization of a hundred thousand
products every list read passes it. Measured on the production stack, the
compiling took 0.3-1 s of each such statement — more than the statement then
took to run — so the production file switches it off. A line lost in an edit
of the database's command would bring that second back silently; this holds
it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def test_the_production_database_runs_with_jit_off():
    compose = yaml.safe_load(
        (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    )
    command = compose['services']['db']['command'].split()
    assert '-c' in command
    settings = {command[i + 1] for i, word in enumerate(command) if word == '-c'}
    assert 'jit=off' in settings
