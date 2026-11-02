"""The cache must actually store what it is given.

``cache_get_or_set`` wraps its write in a try/except so a Redis problem can
never break an endpoint. That is right, and it also meant a serialization bug
was invisible: lists of DTOs raised TypeError on UUID fields, the exception was
swallowed, and the cache silently never populated. Every request recomputed
while the code read as though it were cached.

These tests pin the serializer against the shapes callers actually pass.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.cache import _deserialize, _serialize
from app.core.contracts import UomDTO


def _uom() -> UomDTO:
    return UomDTO(
        id=uuid.uuid4(),
        organization_id=None,
        category_id=uuid.uuid4(),
        name='kilogram',
        symbol='kg',
        factor=1.0,
        is_reference=True,
        is_system=True,
        rounding=0.001,
    )


class TestSerializer:
    def test_a_list_of_dtos_with_uuids_round_trips(self):
        """The regression: this raised TypeError and killed the cache write."""
        dto = _uom()

        restored = _deserialize(_serialize([dto]))

        assert UomDTO.model_validate(restored[0]) == dto

    def test_a_single_dto_round_trips(self):
        dto = _uom()

        assert UomDTO.model_validate(_deserialize(_serialize(dto))) == dto

    def test_an_empty_list_round_trips(self):
        assert _deserialize(_serialize([])) == []

    @pytest.mark.parametrize(
        'value',
        [
            {'id': uuid.uuid4()},
            {'at': datetime.now(UTC)},
            [{'nested': {'id': uuid.uuid4()}}],
        ],
    )
    def test_plain_structures_holding_unserialisable_values_still_encode(self, value):
        """A slightly lossy entry beats a cache that quietly does nothing."""
        assert _deserialize(_serialize(value)) is not None

    def test_ordinary_json_is_untouched(self):
        value = {'count': 3, 'names': ['a', 'b'], 'ok': True, 'missing': None}

        assert _deserialize(_serialize(value)) == value
