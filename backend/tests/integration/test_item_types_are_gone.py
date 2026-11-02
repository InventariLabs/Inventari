"""Item types left the product before the first release.

They had no screen, no row in any organization and no module that declared
one, so keeping them would have published a concept nobody can reach as a
stable contract. This pins the removal: a route, a facade, a manifest field
or a table that comes back has to come back on purpose.
"""

import pytest

from app.core._module_declarations import ModuleMetadata
from app.core.public_api import core_api
from app.database import Base
from app.main import app

pytestmark = pytest.mark.integration


def test_no_route_serves_item_types():
    paths = {getattr(route, 'path', '') for route in app.routes}
    assert not [p for p in paths if 'item-types' in p]


def test_the_core_facade_has_no_item_types_namespace():
    assert not hasattr(core_api, 'item_types')


def test_a_module_cannot_declare_item_types():
    assert 'item_types' not in ModuleMetadata.model_fields


def test_the_models_have_neither_the_table_nor_the_column():
    assert 'item_type_definitions' not in Base.metadata.tables
    assert 'item_type' not in Base.metadata.tables['items'].columns
