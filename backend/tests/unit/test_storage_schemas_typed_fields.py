"""Unit tests for the tightened storage schema.

``StorageLocation.field_definitions`` and
``StorageType.field_definitions`` switch from ``list[Any]`` /
``list[dict[str, Any]]`` to ``list[CategoryFieldDefinition]``.

This closes the untyped gap found in the investigation: malformed entries
(silent accepts at write time, KeyError at render time) become
``ValidationError`` at the API boundary.
"""

import pytest
from pydantic import ValidationError

from app.schemas.storage_location import (
    StorageLocationCreate,
    StorageLocationUpdate,
)
from app.schemas.storage_type import StorageType, StorageTypeCreate, StorageTypeUpdate

# ── StorageLocationCreate / StorageLocationUpdate ─────────────────────


class TestStorageLocationFieldDefinitions:
    def test_valid_field_definition_accepted(self):
        loc = StorageLocationCreate(
            name='Cellar',
            field_definitions=[
                {'key': 'deposit', 'type': 'money', 'label': 'Deposit'},
            ],
        )
        assert loc.field_definitions is not None
        assert loc.field_definitions[0].key == 'deposit'
        assert loc.field_definitions[0].type == 'money'

    def test_malformed_field_definition_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            StorageLocationCreate(
                name='Cellar',
                field_definitions=[{'key': 'x', 'type': 'markdown'}],
            )
        # The "markdown" type is not in the closed Literal.
        assert 'markdown' in str(exc_info.value)

    def test_missing_key_rejected(self):
        with pytest.raises(ValidationError):
            StorageLocationCreate(
                name='Cellar',
                field_definitions=[{'type': 'text', 'label': 'No key'}],
            )

    def test_empty_list_accepted(self):
        loc = StorageLocationCreate(name='Cellar', field_definitions=[])
        assert loc.field_definitions == []

    def test_none_accepted(self):
        loc = StorageLocationCreate(name='Cellar', field_definitions=None)
        assert loc.field_definitions is None

    def test_update_accepts_field_definitions(self):
        upd = StorageLocationUpdate(
            field_definitions=[{'key': 'shelf', 'type': 'text', 'label': 'Shelf'}],
        )
        assert upd.field_definitions is not None
        assert upd.field_definitions[0].key == 'shelf'


# ── StorageTypeCreate / StorageTypeUpdate / StorageType ───────────────


class TestStorageTypeFieldDefinitions:
    def test_valid_field_definition_accepted(self):
        st = StorageTypeCreate(
            name='Wine Cellar',
            type_code='WINE_CELLAR',
            field_definitions=[
                {'key': 'vintage', 'type': 'number', 'label': 'Vintage'}
            ],
        )
        assert st.field_definitions is not None
        assert st.field_definitions[0].type == 'number'

    def test_malformed_field_definition_rejected(self):
        with pytest.raises(ValidationError):
            StorageTypeCreate(
                name='Wine Cellar',
                type_code='WINE_CELLAR',
                field_definitions=[{'key': 'x', 'type': 'markdown'}],
            )

    def test_update_accepts_field_definitions(self):
        upd = StorageTypeUpdate(
            field_definitions=[{'key': 'vintage', 'type': 'number', 'label': 'V'}],
        )
        assert upd.field_definitions is not None

    def test_response_model_typed(self):
        """StorageType (the read-side response) also uses the typed list."""
        from uuid import uuid4

        st = StorageType(
            id=uuid4(),
            name='Wine Cellar',
            type_code='WINE_CELLAR',
            field_definitions=[{'key': 'vintage', 'type': 'number', 'label': 'V'}],
        )
        assert st.field_definitions is not None
        assert st.field_definitions[0].key == 'vintage'
