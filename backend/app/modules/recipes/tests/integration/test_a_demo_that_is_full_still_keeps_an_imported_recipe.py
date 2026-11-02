"""A demo with no room for the cover still saves the recipe it came with.

The cover is fetched and stored after the recipe is committed. When the demo's
upload cap refuses that write, the refusal used to reach the caller as a 413
for a recipe that had in fact been saved, so the client reported a failure and
the user imported it a second time. The cap here is the real one, asked through
the real storage facade; only the remote host is stood in for.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.config import settings
from app.core.file_storage.providers import LocalStorageProvider
from app.core.file_storage.service import FileStorageService
from app.models.user import User
from app.modules.recipes import _recipe_cover
from app.modules.recipes.models import Recipe

RECIPE_URL = '/api/v1/recipes'
COVER_SOURCE = 'https://example.com/dish.png'


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.fixture
def full_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_dns: object
) -> Path:
    """A demo whose upload total is already used up, with the cover host stubbed."""
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
    monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_FILE_MB', 2)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_TOTAL_MB', 1)
    monkeypatch.setattr(
        FileStorageService(), '_provider', LocalStorageProvider(tmp_path), raising=False
    )
    (tmp_path / 'earlier.bin').write_bytes(b'x' * 1024 * 1024)

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=_png(), headers={'content-type': 'image/png'}
        )
    )
    real_fetch = _recipe_cover.fetch_remote_cover

    async def fetch_from_stub(url: str, **_kwargs: Any) -> Any:
        return await real_fetch(url, _transport=transport)

    monkeypatch.setattr(_recipe_cover, 'fetch_remote_cover', fetch_from_stub)
    return tmp_path


@pytest.mark.integration
def test_a_full_demo_saves_the_recipe_without_its_cover(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    full_demo: Path,
) -> None:
    response = client.post(
        RECIPE_URL,
        json={
            'name': 'Imported Pizza',
            'description': '',
            'servings': 2,
            'prep_time_minutes': 30,
            'tags': [],
            'is_favorite': False,
            'ingredients': [],
            'image_source_url': COVER_SOURCE,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()['image_url'] is None

    db_session.expire_all()
    saved = db_session.scalars(
        select(Recipe).where(
            Recipe.organization_id == test_user.organization_id,
            Recipe.name == 'Imported Pizza',
        )
    ).all()
    assert len(saved) == 1
    assert saved[0].image_url is None
    # Nothing was written past the cap either.
    assert sorted(p.name for p in full_demo.rglob('*') if p.is_file()) == [
        '.demo-upload-admission.lock',
        'earlier.bin',
    ]
