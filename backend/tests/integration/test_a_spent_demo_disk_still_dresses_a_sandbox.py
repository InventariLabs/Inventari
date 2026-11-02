"""A sandbox is still dressed when the demo's file storage is full.

The showcase stores a photograph for each demo recipe through the same
storage facade a visitor's upload goes through, and on a demo that facade
admits a write only while the instance total (``DEMO_UPLOAD_TOTAL_MB``) has
room. Every visitor's organization adds its own copies, and visitors upload
into the same total. Once it is spent, the photo step was refused — and with
it the whole sandbox, so the pool stopped refilling and every later visitor
read "try again in a minute" until the reset.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.recipes.models.recipe import Recipe
from seed_demo_showcase import dress_for_visitors
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


def test_the_recipes_go_without_photographs_and_the_rest_is_dressed(
    db_session: Session, demo_world, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    org_id, user_id = ids(demo_world('org-60', seeded_organization(items=60)))
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
    monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_TOTAL_MB', 0)

    summary = dress_for_visitors(db_session, org_id, user_id)

    assert summary['recipe_photos'] == 0
    assert summary['labels'] > 0, 'the rest of the showcase was dressed'
    photographed = db_session.scalars(
        select(Recipe.name).where(
            Recipe.organization_id == org_id, Recipe.image_url.is_not(None)
        )
    ).all()
    assert photographed == []
