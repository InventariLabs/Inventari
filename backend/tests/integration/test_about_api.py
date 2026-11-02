"""GET /api/v1/about — what the in-app About screen shows.

AGPL-3.0 §5(d) asks an interactive interface to show its legal notices, and
§13 asks a modified version served over a network to offer its users the
source. The screen reads both the version and the source link from here.
"""

import tomllib
from pathlib import Path

from fastapi import status

from app.config import settings

_PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'


def _project() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding='utf-8'))['project']


def test_about_reports_the_version_and_licence_pyproject_declares(client, auth_headers):
    response = client.get('/api/v1/about', headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['name'] == 'Inventari'
    assert body['version'] == _project()['version']
    assert body['license'] == _project()['license']
    assert body['license_url'] == 'https://www.gnu.org/licenses/agpl-3.0.html'


def test_the_source_link_defaults_to_the_project_repository(client, auth_headers):
    response = client.get('/api/v1/about', headers=auth_headers)

    assert response.json()['source_code_url'] == (
        'https://github.com/InventariLabs/Inventari'
    )


def test_an_instance_points_the_source_link_at_its_own_fork(
    client, auth_headers, monkeypatch
):
    # §13: whoever runs a modified version offers *its* source, and does so
    # by configuration, not by editing the screen.
    monkeypatch.setattr(
        settings, 'SOURCE_CODE_URL', 'https://git.example.org/acme/inventari'
    )

    response = client.get('/api/v1/about', headers=auth_headers)

    assert (
        response.json()['source_code_url'] == 'https://git.example.org/acme/inventari'
    )


def test_a_blank_setting_falls_back_to_the_project_repository(
    client, auth_headers, monkeypatch
):
    # `.env.production.example` ships the line empty; an empty link would
    # offer the source of nothing.
    monkeypatch.setattr(settings, 'SOURCE_CODE_URL', '  ')

    response = client.get('/api/v1/about', headers=auth_headers)

    assert response.json()['source_code_url'] == (
        'https://github.com/InventariLabs/Inventari'
    )


def test_about_needs_a_signed_in_user(client):
    response = client.get('/api/v1/about')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
