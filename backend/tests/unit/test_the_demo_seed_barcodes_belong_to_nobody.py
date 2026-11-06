"""Every barcode the demo seeder writes comes from the GS1 restricted range.

docs/DEMO.md promises the demo carries nothing that belongs to anybody: its
barcodes are drawn from the range GS1 reserves for in-store use ("2" prefix),
which is never allocated to a real product. The equipment templates once
carried the prefixes of the manufacturers they are named after (Dell, Apple,
Logitech...), so scanning a printed demo label read as that firm's product,
and most of them failed the check digit besides.
"""

from __future__ import annotations

import pytest

from app.core.barcode import validate_checksum
from seed_demo_data import EQUIPMENT_TEMPLATES, FOOD_TEMPLATES, MAKER_BARCODES

_SEEDED = (
    [(name, code) for name, _brand, code, *_rest in FOOD_TEMPLATES]
    + [(name, code) for name, _brand, code, *_rest in EQUIPMENT_TEMPLATES]
    + list(MAKER_BARCODES.items())
)


def test_the_corpus_is_not_empty() -> None:
    assert len(EQUIPMENT_TEMPLATES) >= 26
    assert len(_SEEDED) >= 100


@pytest.mark.parametrize(('name', 'code'), [(n, c) for n, c in _SEEDED if c])
def test_a_seeded_barcode_is_restricted_range_and_valid(name: str, code: str) -> None:
    assert code.startswith('2'), f'{name}: {code} is outside the GS1 restricted range'
    assert validate_checksum(code), f'{name}: {code} has a wrong check digit'


def test_no_two_templates_share_a_barcode() -> None:
    codes = [c for _n, c in _SEEDED if c]
    assert len(codes) == len(set(codes))
