"""The version the health endpoints report is the one pyproject.toml declares."""

import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'


@pytest.mark.parametrize('path', ['/', '/health'])
def test_health_reports_the_pyproject_version(client, path):
    declared = tomllib.loads(_PYPROJECT.read_text(encoding='utf-8'))['project'][
        'version'
    ]

    response = client.get(path)

    assert response.status_code == 200
    assert response.json()['version'] == declared
