"""Every photograph the demo ships says where it came from and may be shipped.

The recipe photos live in the repository (``seed_assets/demo_recipes``) and the
demo reset stores them as each recipe's cover. A picture in a public tree is a
licence question before it is a design one, so the manifest beside the files is
the record: the page each one was taken from, its author where one is named,
and a licence that asks nothing of whoever copies the tree. A file added
without a row, or a row naming a licence that needs attribution or forbids
redistribution, fails here rather than in somebody's takedown request.
"""

from __future__ import annotations

import json

from seed_demo_data import DEMO_RECIPES
from seed_demo_showcase import DEMO_RECIPE_PHOTOS

#: Licences that need no notice and allow redistribution and modification.
FREE_TO_SHIP = {'CC0-1.0'}


def _manifest() -> list[dict]:
    return json.loads((DEMO_RECIPE_PHOTOS / 'sources.json').read_text())['photos']


def test_every_photo_names_its_source_and_a_licence_that_asks_nothing():
    rows = _manifest()
    assert rows, 'the manifest lists no photograph'
    for row in rows:
        assert row['licence'] in FREE_TO_SHIP, row
        assert row['page'].startswith('https://'), row
        assert row['original'].startswith('https://'), row


def test_the_manifest_and_the_directory_agree():
    listed = {row['file'] for row in _manifest()}
    shipped = {path.name for path in DEMO_RECIPE_PHOTOS.glob('*.jpg')}
    assert listed == shipped


def test_every_demo_recipe_has_exactly_one_photo():
    named = [row['recipe'] for row in _manifest()]
    assert sorted(named) == sorted(row[0] for row in DEMO_RECIPES)
